"""
preprocessing.py
================
Homogeneiza las imágenes descargadas a un formato común.

  - Valida dimensiones, CRS, resolución, alineación espacial
  - Remuestrea bandas de 20/60 m a resolución objetivo (por defecto 10 m)
  - Manejo de NoData
  - Asegura que todas las bandas terminan con HxW idénticas
  - Mantiene información geográfica

La resolución objetivo se toma de cfg.sentinel.resolution (m).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import rasterio
from rasterio.crs import CRS as RioCRS
from rasterio.enums import Resampling
from rasterio.io import DatasetReader
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, reproject

logger = logging.getLogger(__name__)


EXPECTED_BANDS_COUNT = 12


def validate_target_image(path: str | Path, expected_bands: Iterable[str]) -> dict:
    """Valida que un GeoTIFF multibanda cumpla expectativas mínimas.

    Devuelve dict con profile resumido + band descriptions.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe la imagen: {path}")
    with rasterio.open(path) as src:
        n_bands = src.count
        if n_bands != len(list(expected_bands)):
            logger.warning(
                "%s tiene %d bandas, se esperaban %d (%s)",
                path.name,
                n_bands,
                len(list(expected_bands)),
                list(expected_bands),
            )
        crs_ok = src.crs is not None
        transform_ok = src.transform is not None
        return {
            "path": str(path),
            "exists": True,
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "dtype": src.dtypes[0],
            "crs": str(src.crs) if src.crs else None,
            "crs_ok": crs_ok,
            "transform_ok": transform_ok,
            "nodata": src.nodata,
            "resolution": src.res,
            "bounds": list(src.bounds),
            "band_descriptions": list(src.descriptions),
        }


def _resample_to_resolution(
    src: DatasetReader,
    target_resolution_m: float,
    target_crs_epsg: int = 4326,
) -> tuple[np.ndarray, dict]:
    """Remuestrea todas las bandas del raster a la resolución objetivo.

    Utiliza WarpedVRT + reproyección para garantizar dimensiones y CRS uniformes.
    """
    target_crs = RioCRS.from_epsg(target_crs_epsg)

    # Primero: proyectar a WGS84 si no lo está, y resolver resolución en grados
    # Aproximación: 1 m ≈ 9.0e-6 grados (en latitudes ~6-8 N)
    resolution_deg = target_resolution_m * 9.0e-6

    if src.crs is None:
        src_crs = target_crs
        logger.warning("CRS faltante en %s. Asumiendo WGS84.", src.name)
    else:
        src_crs = src.crs

    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs,
        target_crs,
        src.width,
        src.height,
        *src.bounds,
        resolution=resolution_deg,
    )

    dst_profile = {
        "driver": src.driver,
        "height": dst_height,
        "width": dst_width,
        "count": src.count,
        "dtype": src.dtypes[0],
        "crs": target_crs,
        "transform": dst_transform,
        "nodata": src.nodata,
    }

    dst = np.zeros((src.count, dst_height, dst_width), dtype=src.dtypes[0])
    for band_idx in range(1, src.count + 1):
        reproject(
            source=rasterio.band(src, band_idx),
            destination=dst[band_idx - 1],
            src_transform=src.transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=target_crs,
            resampling=Resampling.bilinear,
            src_nodata=src.nodata,
            dst_nodata=src.nodata,
        )
    return dst, dst_profile


def ensure_uniform_image(
    input_tif: str | Path,
    output_tif: str | Path,
    *,
    target_resolution_m: int,
    expected_bands: Iterable[str],
    target_crs_epsg: int = 4326,
) -> Path:
    """Asegura que la imagen final tenga resolución, CRS y dimensiones uniformes.

    Returns:
        Ruta del GeoTIFF resultante (normalmente la misma que output_tif).
    """
    input_tif = Path(input_tif)
    output_tif = Path(output_tif)
    output_tif.parent.mkdir(parents=True, exist_ok=True)

    expected_bands = list(expected_bands)

    with rasterio.open(input_tif) as src:
        # Detectar si requiere remuestreo
        needs_resample = False
        if src.crs is None or not src.crs.equals(RioCRS.from_epsg(target_crs_epsg)):
            needs_resample = True
        res = src.res
        if res is not None and len(res) == 2:
            # src.res viene en unidades del CRS (grados en WGS84)
            res_m_approx_x = res[0] / 9.0e-6 if abs(res[0]) < 1 else res[0]
            if abs(res_m_approx_x - target_resolution_m) > 0.5:
                needs_resample = True
        if src.count != len(expected_bands):
            needs_resample = True

        if not needs_resample and input_tif == output_tif:
            logger.debug("Imagen %s ya cumple requisitos. Sin cambios.", input_tif.name)
            return input_tif

        if needs_resample:
            logger.info(
                "Remuestreando %s -> %s (res=%dm, CRS=EPSG:%d, bands=%d)",
                input_tif.name,
                output_tif.name,
                target_resolution_m,
                target_crs_epsg,
                len(expected_bands),
            )
            arr, profile = _resample_to_resolution(src, target_resolution_m, target_crs_epsg)
        else:
            arr = src.read()
            profile = src.profile.copy()

        # Asegurar band descriptions
        profile["count"] = min(arr.shape[0], len(expected_bands))
        profile["height"] = arr.shape[1]
        profile["width"] = arr.shape[2]
        profile["driver"] = "GTiff"

        with rasterio.open(output_tif, "w", **profile) as dst:
            for i, name in enumerate(expected_bands[: profile["count"]], start=1):
                dst.write(arr[i - 1], i)
                dst.set_band_description(i, str(name))
        logger.info(
            "Imagen preprocesada guardada: %s (%dx%d px, %d bandas)",
            output_tif.name,
            profile["width"],
            profile["height"],
            profile["count"],
        )
    return output_tif
