"""
downloader.py
=============
Descarga de bandas Sentinel-2 L2A vía Process API (Sentinel Hub).

  - Endpoint: https://sh.dataspace.copernicus.eu/process/v1
  - 12 bandas L2A: B01, B02, B03, B04, B05, B06, B07, B08, B8A, B09, B11, B12
  - Resolución configurable (por defecto 10 m)
  - Solo descarga el AOI de la parcela (NO la escena completa)
  - Salida: GeoTIFF multibanda en data/processed/palma/PALMA_XXXX/YYYY-MM.tif

NO se solicita B10, ya que no pertenece a las bandas de superficie L2A.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np
import rasterio
from rasterio.crs import CRS as RioCRS
from rasterio.transform import from_bounds

from sentinelhub import (
    BBox,
    CRS,
    DataCollection,
    MimeType,
    SentinelHubRequest,
    bbox_to_dimensions,
)
from sentinelhub.data_collections_bands import Band

from .config import AppConfig
from .auth import get_auth
from .aoi_generator import get_bbox_wgs84


logger = logging.getLogger(__name__)


# Sentinel-2 L2A: 12 bandas de superficie (B10 NO incluido)
# Orden en el GeoTIFF de salida (idéntico al config.yaml)
L2A_BANDS = [
    "B01", "B02", "B03", "B04", "B05", "B06",
    "B07", "B08", "B8A", "B09", "B11", "B12",
]


def _build_evalscript(bands: list[str]) -> str:
    """Evalscript simple: devuelve todas las bandas en orden con reflectancias 0-10000 o raw UINT16.
    Aquí pedimos reflectancia (FLOAT32) para luego poder guardarla.
    """
    joined_bands = ",".join(f'"{b}"' for b in bands)
    sample_entries = ",\n".join(
        f'      {{id: "{b}", bands: ["{b}"]}}' for b in bands
    )
    # Utilizamos setup de reflectancia para garantizar números físicamente interpretables
    script = f"""
//VERSION=3
function setup() {{
  return {{
    input: [
{{
      datasource: "s2l2a",
      bands: [{joined_bands}],
      units: "reflectance"
    }}
  ],
    output: [
{sample_entries},
      {{id: "SCL", bands: ["SCL"]}}
    ]
  }};
}}

function evaluatePixel(sample) {{
  var s2l2a = sample.s2l2a[0];
  var out = {{}};
  var anyBands = [{joined_bands}];
  anyBands.forEach(b => {{ out[b] = s2l2a[b]; }});
  out["SCL"] = s2l2a.SCL;
  return out;
}}
"""
    return script


def _build_evalscript_single_output(bands: list[str]) -> str:
    """Evalscript Process API standard (Sentinel-2 L2A, formato DN universal).

    MOTIVACIÓN "DN" y no "REFLECTANCE":
    En Copernicus CDSE, la banda SCL (Scene Classification) NO admite units="REFLECTANCE"
    → HTTP 400: Band 'SCL' of collection 'S2L2A' requested in unsupported units 'REFLECTANCE'!
       Supported units for this band: DN.
    Por tanto usamos units="DN" para todas las bandas. Valores resultantes:
    - Bandas reflectancia (B01..B12): DN 0..10000 → dividir por 10000.0 para [0,1] (float).
      Lo hacemos en post-procesado del array (abajo, download_monthly_image).
    - Banda SCL (última): DN 0..11 (uint8).
    """
    n = len(bands)
    bands_list = ", ".join(f'"{b}"' for b in bands)
    return f"""
//VERSION=3
function setup() {{
  return {{
    input: [{{
      bands: [{bands_list}, "SCL"],
      units: "DN"
    }}],
    output: [{{
      id: "DEFAULT",
      bands: {n + 1},
      sampleType: "FLOAT32"
    }}]
  }};
}}

function evaluatePixel(sample) {{
  return [
    {", ".join(f"sample.{b}" for b in bands)},
    sample.SCL
  ];
}}
"""


def _parcel_dir(cfg: AppConfig, crop_id: str) -> Path:
    d = cfg.output.crop_dir_abs / crop_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _image_filename(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}.tif"


def _cloud_mask_filename(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}_cloud_mask.tif"


def download_monthly_image(
    cfg: AppConfig,
    *,
    parcel_row: Any,
    selection: Any,  # MonthlySelection
) -> tuple[Optional[Path], Optional[Path]]:
    """Descarga una imagen mensual y (opcionalmente) su cloud mask derivada.

    Returns:
        (ruta_tif_multibanda, ruta_cloud_mask) o (None, None) si no está disponible.
    """
    if selection.status != "available":
        logger.info(
            "  [skip] %s mes %04d-%02d: status=%s",
            selection.crop_id,
            selection.year,
            selection.month,
            selection.status,
        )
        return None, None

    crop_id = selection.crop_id
    year = selection.year
    month = selection.month

    parcel_dir = _parcel_dir(cfg, crop_id)
    out_tif = parcel_dir / _image_filename(year, month)
    out_mask = parcel_dir / _cloud_mask_filename(year, month)

    if out_tif.exists():
        logger.info("  [cache] %s ya existe. Saltando descarga.", out_tif.name)
        if not out_mask.exists():
            # Reintentamos solo la cloud mask si hiciera falta (lazy)
            pass
        return out_tif, out_mask if out_mask.exists() else None

    auth = get_auth()
    sh_config = auth.get_sh_config()

    # === IMPORTANTE (FIX 401 Unauthorized):
    # DataCollection.SENTINEL2_L2A por defecto apunta a services.sentinel-hub.com (antiguo).
    # Nosotros usamos Copernicus Data Space (CDSE), así que definimos explícitamente la
    # colección con sh_config.sh_base_url = https://sh.dataspace.copernicus.eu
    # Ref: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Overview.html
    s2l2a_collection = DataCollection.SENTINEL2_L2A.define_from(
        name="S2L2A_CDSE",
        service_url=sh_config.sh_base_url,
        wfs_id="DSS2",
    )

    logger.info("  DataCollection.service_url = %s", sh_config.sh_base_url)

    # Ventana +/- 5 días alrededor de la fecha de adquisición para robustecer
    acq_date_str = selection.acquisition_date or f"{year}-{month:02d}-15"
    try:
        acq = datetime.fromisoformat(acq_date_str.replace("Z", "+00:00"))
    except ValueError:
        acq = datetime(year, month, 15)

    time_interval = (
        f"{acq.year:04d}-{acq.month:02d}-{max(1, acq.day - 5):02d}T00:00:00Z",
        f"{acq.year:04d}-{acq.month:02d}-{min(31, acq.day + 5):02d}T23:59:59Z",
    )

    # BBox WGS84 -> convertimos a UTM si la resolución está en metros (sentinelhub lo requiere)
    minx, miny, maxx, maxy = get_bbox_wgs84(parcel_row.geometry)
    bbox_wgs84 = BBox(bbox=[minx, miny, maxx, maxy], crs=CRS.WGS84)

    # Dimensiones en píxeles aprox (solo para estimar tamaño)
    resolution_m = int(cfg.sentinel.resolution)
    dimensions = bbox_to_dimensions(bbox_wgs84, resolution=resolution_m)

    bands = list(cfg.sentinel.bands) or list(L2A_BANDS)
    if "SCL" in bands:
        bands = [b for b in bands if b != "SCL"]

    # DataCollection: Sentinel-2 L2A en Copernicus Dataspace (ya se definió arriba)
    evalscript = _build_evalscript_single_output(bands)

    logger.info(
        "  Descargando %s-%02d para %s (dims=%s, res=%dm, %d bandas+SCL)...",
        year,
        month,
        crop_id,
        dimensions,
        resolution_m,
        len(bands),
    )

    try:
        # 1 salida: DEFAULT (bandas reflectancia + SCL)
        request = SentinelHubRequest(
            data_folder=str(parcel_dir),
            evalscript=evalscript,
            input_data=[
                SentinelHubRequest.input_data(
                    data_collection=s2l2a_collection,
                    time_interval=time_interval,
                    maxcc=float(cfg.sentinel.max_cloud_cover) / 100.0,
                    other_args={"dataFilter": {"mosaickingOrder": "leastCC"}},
                )
            ],
            responses=[
                SentinelHubRequest.output_response("DEFAULT", MimeType.TIFF),
            ],
            bbox=bbox_wgs84,
            size=dimensions,
            config=sh_config,
        )

        data_list = request.get_data(save_data=False, show_progress=False)
        if not data_list:
            raise RuntimeError("SentinelHubRequest devolvió datos vacíos.")
        arr = data_list[0]
        if isinstance(arr, list):
            arr = arr[0]
        arr = np.asarray(arr)
        if arr.ndim == 2:
            arr = arr[np.newaxis, :, :]
        elif arr.ndim == 3:
            # Si viene (H, W, B) -> (B, H, W)
            if arr.shape[0] != arr.shape[1]:
                arr = np.transpose(arr, (2, 0, 1))

        n_bands_total = arr.shape[0]
        expected = len(bands) + 1
        if n_bands_total != expected:
            logger.warning(
                "Cantidad de bandas descargadas %d != esperadas %d. Ajustando...",
                n_bands_total, expected,
            )
            if n_bands_total > expected:
                arr = arr[:expected]
            else:
                raise RuntimeError(
                    f"Se esperaban {expected} bandas, descargadas {n_bands_total}"
                )

        reflectance = arr[: len(bands)]
        scl = arr[len(bands)] if n_bands_total > len(bands) else None

        # IMPORTANTE: Evalscript usó units="DN" (por compatibilidad con SCL).
        # Reflectancia Sentinel-2 L2A DN = 0..10000. Dividir por 10000.0
        # para rango físico reflectancia [0, 1] (float). NoData pasa a ser NaN.
        # SCL la dejamos en DN uint8 (0..11) para clasificación.
        reflectance = reflectance.astype(np.float32) / 10000.0

        # Convertir valores negativos/NoData de DN a NaN
        reflectance[reflectance < 0] = np.nan

        # Guardar imagen multibanda
        profile = {
            "driver": cfg.output.format,
            "height": reflectance.shape[1],
            "width": reflectance.shape[2],
            "count": reflectance.shape[0],
            "dtype": str(reflectance.dtype),
            "crs": RioCRS.from_epsg(4326),
            "transform": from_bounds(minx, miny, maxx, maxy, reflectance.shape[2], reflectance.shape[1]),
            "nodata": np.nan if np.issubdtype(reflectance.dtype, np.floating) else 0,
        }
        with rasterio.open(out_tif, "w", **profile) as dst:
            for i, b_name in enumerate(bands, start=1):
                dst.write(reflectance[i - 1], i)
                dst.set_band_description(i, b_name)
        logger.info("  OK -> %s (%dx%d px, %d bandas, %.1f MB)",
                    out_tif.name,
                    reflectance.shape[2],
                    reflectance.shape[1],
                    reflectance.shape[0],
                    out_tif.stat().st_size / (1024 * 1024),
                    )

        # Guardar cloud mask por ahora desde SCL si está disponible
        mask_path: Optional[Path] = None
        if scl is not None:
            from .cloud_mask import build_cloud_mask_from_scl
            mask = build_cloud_mask_from_scl(scl.astype(np.uint8))
            mask_profile = {
                "driver": cfg.output.format,
                "height": mask.shape[0],
                "width": mask.shape[1],
                "count": 1,
                "dtype": str(mask.dtype),
                "crs": profile["crs"],
                "transform": profile["transform"],
                "nodata": 255,
            }
            with rasterio.open(out_mask, "w", **mask_profile) as dst:
                dst.write(mask, 1)
                dst.set_band_description(1, "CLOUD_MASK")
            mask_path = out_mask
            logger.info("  Cloud mask guardada en %s", out_mask.name)

        return out_tif, mask_path

    except Exception as e:
        logger.exception(
            "Fallo descargando imagen para %s %04d-%02d: %s", crop_id, year, month, e
        )
        raise
