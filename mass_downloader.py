"""mass_downloader.py - VERSIÓN LIMPIA

Descarga MASIVA con ESTRUCTURA NUEVA pedida por el usuario:

Estructura:
    data/mass_dataset_palma_YYYY/
    └── YYYY-MM-DD_HHMMSS_<lon>_<lat>/            ← 1 carpeta por muestra
        ├── 12bands.tif                            ← GeoTIFF multibanda (12 bandas, 10 m, EPSG:4326, float32 [0,1])
        ├── cloud_mask.tif                         ← uint8 1=valid 0=invalid 255=nodata
        └── metadata.json                          ← crop_id / fecha hora / class / area / bbox / product / cloud

Soporta:
    • checkpoint CSV (skip muestra ya procesada)
    • reintentos HTTP por excepción sentinelhub
    • paralelización workers (default 3)
    • resumen antes de ejecutar (size GB + horas + confirmación s/N o flag -y)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import sys
import time
import warnings
import datetime as _dt
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import geopandas as gpd
import numpy as np
import rasterio
import tqdm
from rasterio.crs import CRS as RioCRS
from rasterio.transform import from_bounds

import sentinelhub
from sentinelhub import (
    BBox,
    CRS,
    DataCollection,
    MimeType,
    SentinelHubRequest,
    bbox_to_dimensions,
)
from sentinelhub.exceptions import DownloadFailedException

# ---- Logging --------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MASSDL")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---- Proyecto src --------------------------------------------------------
from src.config import AppConfig, load_config
from src.aoi_generator import load_aoi_gdf, repair_geometries, get_bbox_wgs84
from src.catalog import search_sentinel
from src.image_selector import _parse_start_end, _month_interval, _pick_best
from src.downloader import L2A_BANDS
from src.auth import get_auth
from src.metadata import ImageMetadata, save_image_metadata
from src import cloud_mask as cm

# ---- Utils nombres seguros ----------------------------------------------
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe(s: str) -> str:
    return _SAFE_RE.sub("_", s)


def _sample_folder_name(
    acquisition_date: str,
    acquisition_time_str: str,
    bbox_wgs84: tuple[float, float, float, float],
) -> str:
    """Nombre = YYYY-MM-DD_HHMMSS_lonmin_latmin_lonmax_latmax

    Convertimos signos: '-' -> 'm'  '.' -> 'p'  para que sea Windows-seguro.
    Ej: 2024-01-22_152649_m73p9073_7p2464_m73p8197_7p3188
    """
    d = acquisition_date.replace("/", "-")
    h = (acquisition_time_str or "000000").replace(":", "")[:6].ljust(6, "0")
    minx, miny, maxx, maxy = bbox_wgs84

    def fmt(v: float) -> str:
        # signo + 4 decimales
        sign = "m" if v < 0 else "p"
        return f"{sign}{abs(v):.4f}".replace(".", "p")

    coords = "_".join(fmt(v) for v in (minx, miny, maxx, maxy))
    return f"{d}_{h}_{coords}"


# ---- Evalscript Process API CDSE (S2 L2A DN units = universal) ----------
def _build_evalscript_dn(bands: Iterable[str]) -> str:
    bands = list(bands)
    n = len(bands)
    bands_quoted = ", ".join(f'"{b}"' for b in bands)
    return (
        "//VERSION=3\n"
        "function setup() {\n"
        f"  return {{ input: [{{ bands: [{bands_quoted}, 'SCL'], units: 'DN' }}],\n"
        f"           output: [{{ id: 'DEFAULT', bands: {n + 1}, sampleType: 'FLOAT32' }}] }};\n"
        "}\n"
        "function evaluatePixel(s) {\n"
        "  return [" + ", ".join(f"s.{b}" for b in bands) + ", s.SCL ];\n"
        "}\n"
    )


# ---- Result ---------------------------------------------------------------
@dataclass
class DownloadResult:
    sample_folder: str
    crop_id: str
    status: str                      # ok, skip_exists, error
    error: Optional[str] = None
    path_12bands: Optional[str] = None
    path_mask: Optional[str] = None
    path_meta: Optional[str] = None
    mb_12bands: Optional[float] = None
    cloud_local_pct: Optional[float] = None


def _retry_call(fn, *, max_retries: int = 4, base_backoff: float = 3.0):
    """Llama fn() con reintento exponencial."""
    last: Optional[BaseException] = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            wait = base_backoff ** attempt
            logger.warning("reintento %d/%d en %.1fs: %s", attempt, max_retries, wait, str(exc)[:120])
            time.sleep(wait)
    raise last  # type: ignore[misc]


# ---- Catalog build --------------------------------------------------------
def _samples_for_parcel(cfg: AppConfig, parcel_row: gpd.GeoDataFrame) -> list[dict[str, Any]]:
    row = parcel_row.iloc[0]
    crop_id = str(row["crop_id"])
    bbox = tuple(float(x) for x in get_bbox_wgs84(row.geometry))
    months = _parse_start_end(cfg.temporal.start_date, cfg.temporal.end_date)
    out: list[dict[str, Any]] = []
    for (y, m) in months:
        s, e = _month_interval(y, m)
        try:
            items = search_sentinel(
                cfg,
                bbox=list(bbox),
                start_date=s,
                end_date=e,
                max_pages=3,
            )
        except Exception as exc:
            logger.warning("Catalog %s %04d-%02d ERROR: %s", crop_id, y, m, str(exc)[:140])
            continue
        best = _pick_best(items)
        if best is None:
            continue
        dt_iso = str(best.get("datetime") or "")
        date_part = dt_iso[:10] or f"{y:04d}-{m:02d}-01"
        time_part = dt_iso[11:19].replace(":", "") if len(dt_iso) >= 19 else "000000"
        time_part = time_part.ljust(6, "0")
        out.append({
            "crop_id": crop_id,
            "crop_type": "oil_palm",
            "class": int(row["class"]),
            "class_name": str(row["class_name"]),
            "area_ha": float(row["area_ha"]),
            "year": int(y),
            "month": int(m),
            "acquisition_date": date_part,
            "acquisition_time_str": time_part,
            "acquisition_datetime_iso": dt_iso,
            "bbox_wgs84": list(bbox),
            "product_id": str(best.get("product_id") or best.get("id") or ""),
            "scene_cloud_cover_pct": float(best.get("cloud_cover") or 0.0),
            "item_id": str(best.get("id") or ""),
        })
    return out


# ---- Download one ---------------------------------------------------------
def _download_sample(
    cfg: AppConfig,
    sample: dict[str, Any],
    output_root: Path,
    overwrite: bool = False,
) -> DownloadResult:
    crop_id = sample["crop_id"]
    bbox = tuple(float(x) for x in sample["bbox_wgs84"])  # WGS84 minx miny maxx maxy
    folder = _sample_folder_name(
        sample["acquisition_date"], sample["acquisition_time_str"], bbox
    )
    sample_dir = output_root / folder
    meta_json = sample_dir / "metadata.json"
    # Skip logic: reconocer nuevo formato 12 bandas individuales (A_B04_(Raw).tiff + metadata)
    primary_band = sample_dir / "A_B04_(Raw).tiff"
    legacy_12bands = sample_dir / "12bands.tif"
    if (meta_json.exists() and (primary_band.exists() or legacy_12bands.exists())) and not overwrite:
        return DownloadResult(
            sample_folder=folder,
            crop_id=crop_id,
            status="skip_exists",
            path_12bands=str(primary_band if primary_band.exists() else legacy_12bands),
            path_mask=str(sample_dir / "cloud_mask.tif"),
            path_meta=str(meta_json),
        )

    try:
        sample_dir.mkdir(parents=True, exist_ok=True)

        # 1) auth y data collection CDSE
        auth = get_auth()
        sh_config = auth.get_sh_config()
        s2l2a_cdse = DataCollection.SENTINEL2_L2A.define_from(
            name="S2L2A_CDSE_MASS",
            service_url=sh_config.sh_base_url,
            wfs_id="DSS2",
        )
        bbox_obj = BBox(bbox=bbox, crs=CRS.WGS84)
        dims = bbox_to_dimensions(bbox_obj, resolution=cfg.sentinel.resolution)
        evalscript = _build_evalscript_dn(L2A_BANDS)

        # carpeta TEMPORAL para data_folder SENTINELHUB (CORTO PATH para evitar warning 255 chars)
        # Se usa hash corto (8 chars) + sample_dir tmp para que el path total sea <200 y response.tiff no warning
        _tmp_root = PROJECT_ROOT / "data" / ".sh_tmp"
        _tmp_root.mkdir(parents=True, exist_ok=True)
        _folder_id = hashlib.md5((crop_id + "|" + folder).encode("utf-8", errors="replace")).hexdigest()[:10]
        _data_folder = _tmp_root / _folder_id
        _data_folder.mkdir(parents=True, exist_ok=True)
        # Suprimir warnings inocuos (path largo + rate limit) dentro de call Sentinel para no asustar
        _sw = warnings.catch_warnings()
        _sw.__enter__()
        try:
            warnings.filterwarnings("ignore", message=r"File path.*longer than 255 character", category=Warning)
            warnings.filterwarnings("ignore", message=r"Download rate limit hit", category=Warning)

            # 2) ventana de fecha ± 5 días
            d0 = _dt.date.fromisoformat(sample["acquisition_date"])
            t0 = (d0 - _dt.timedelta(days=5)).isoformat()
            t1 = (d0 + _dt.timedelta(days=5)).isoformat()

            def _process_call():
                req = SentinelHubRequest(
                    data_folder=str(_data_folder),
                    evalscript=evalscript,
                    input_data=[
                        SentinelHubRequest.input_data(
                            data_collection=s2l2a_cdse,
                            time_interval=(t0, t1),
                            maxcc=float(cfg.sentinel.max_cloud_cover) / 100.0,
                            other_args={"dataFilter": {"mosaickingOrder": "leastCC"}},
                        )
                    ],
                    responses=[SentinelHubRequest.output_response("DEFAULT", MimeType.TIFF)],
                    bbox=bbox_obj,
                    size=dims,
                    config=sh_config,
                )
                return req.get_data(save_data=False, show_progress=False)

            data_list = _retry_call(_process_call)
        finally:
            _sw.__exit__(None, None, None)
            # Limpiar carpeta temporal para ahorrar espacio (el response.tiff ya no hace falta en data_list con save_data=False)
            try:
                if _data_folder.exists():
                    import shutil as _shutil
                    _shutil.rmtree(_data_folder, ignore_errors=True)
            except Exception:
                pass

        if not data_list:
            raise RuntimeError("SentinelHubRequest devolvió lista vacía.")
        arr = np.asarray(data_list[0])
        if arr.ndim == 2:
            arr = arr[np.newaxis, :, :]
        elif arr.ndim == 3:
            # Caso (H,W,B) -> (B,H,W)
            if arr.shape[0] == arr.shape[1]:
                pass  # ya (B,H,W) muy raro.
            if arr.shape[0] != arr.shape[1] and arr.shape[2] in {len(L2A_BANDS) + 1, len(L2A_BANDS) + 0}:
                arr = np.transpose(arr, (2, 0, 1))
        expected = len(L2A_BANDS) + 1
        if arr.shape[0] > expected:
            arr = arr[:expected]
        if arr.shape[0] != expected:
            raise RuntimeError(f"Bandas descargadas {arr.shape[0]}, esperadas {expected}")

        reflect = arr[: len(L2A_BANDS)].astype(np.float32) / 10000.0
        reflect[reflect < 0] = np.nan
        scl = np.clip(np.round(arr[len(L2A_BANDS)]), 0, 11).astype(np.uint8)

        # 3) 12 bandas INDIVIDUALES (B01_(Raw).tiff ... B12_(Raw).tiff) — como en la imagen
        minx, miny, maxx, maxy = bbox
        H, W = reflect.shape[1], reflect.shape[2]
        transform = from_bounds(minx, miny, maxx, maxy, W, H)

        def _common_profile_1b(dtype: str, nodata_val: Any) -> dict[str, Any]:
            return {
                "driver": "GTiff",
                "height": H, "width": W,
                "count": 1,
                "dtype": dtype,
                "crs": RioCRS.from_epsg(4326),
                "transform": transform,
                "nodata": nodata_val,
            }

        band_paths: list[Path] = []
        total_mb = 0.0
        for i, bname in enumerate(L2A_BANDS):
            # B01_(Raw).tiff (igual nomenclatura que la captura de referencia)
            fname = f"A_{bname}_(Raw).tiff"
            path_b = sample_dir / fname
            band_arr = reflect[i].astype(np.float32)
            with rasterio.open(path_b, "w", **_common_profile_1b("float32", np.nan)) as dst:
                dst.write(band_arr, 1)
                dst.set_band_description(1, f"{bname} surface reflectance DN/10000")
            band_paths.append(path_b)
            try:
                total_mb += path_b.stat().st_size / (1024 * 1024)
            except OSError:
                pass

        # 3b) A_True_Color.tiff RGB (B04=R, B03=G, B02=B, stretch 2-98 percentil, uint8)
        idx_r = L2A_BANDS.index("B04")
        idx_g = L2A_BANDS.index("B03")
        idx_b = L2A_BANDS.index("B02")
        true_color_path = sample_dir / "A_True_Color.tiff"
        try:
            rgb_stack = np.stack([reflect[idx_r], reflect[idx_g], reflect[idx_b]], axis=0).astype(np.float32)  # (3,H,W)
            rgb_uint8 = np.zeros_like(rgb_stack, dtype=np.uint8)
            for ch in range(3):
                band = rgb_stack[ch]
                valid = band[np.isfinite(band) & (band > 0)]
                if valid.size < 100:
                    # Fallback stretch: rango típico palma aceitera B02-B04 reflectancia 0.02 - 0.3
                    p2, p98 = 0.02, 0.30
                else:
                    p2 = float(np.percentile(valid, 2))
                    p98 = float(np.percentile(valid, 98))
                    # Fallback si el rango es demasiado pequeño (ej: demasiados píxeles oscuros iguales)
                    if p98 - p2 < 0.005:
                        p2 = max(0.0, p2 - 0.01)
                        p98 = p2 + 0.25
                scaled = np.clip((band - p2) / max(1e-6, (p98 - p2)) * 255.0, 0, 255)
                rgb_uint8[ch] = np.where(np.isfinite(band), scaled.astype(np.uint8), 0)
            with rasterio.open(
                true_color_path, "w",
                driver="GTiff",
                height=H, width=W,
                count=3, dtype="uint8",
                crs=RioCRS.from_epsg(4326),
                transform=transform,
                nodata=0,
            ) as dst:
                dst.set_band_description(1, "R = B04 (stretch 2-98%)")
                dst.set_band_description(2, "G = B03 (stretch 2-98%)")
                dst.set_band_description(3, "B = B02 (stretch 2-98%)")
                for ch in range(3):
                    dst.write(rgb_uint8[ch], ch + 1)
            try:
                total_mb += true_color_path.stat().st_size / (1024 * 1024)
            except OSError:
                pass
        except Exception as e:
            logger.warning("True color fallo para %s: %s (continuando)", folder, str(e)[:100])

        # 4) cloud_mask.tif (mantener igual, mismo formato y transform)
        mask_arr = cm.build_cloud_mask_from_scl(scl.astype(np.uint8))
        local_pct = cm.compute_pixel_cloud_cover_from_mask(mask_arr)
        path_mask = sample_dir / "cloud_mask.tif"
        with rasterio.open(
            path_mask, "w",
            driver="GTiff",
            height=mask_arr.shape[0], width=mask_arr.shape[1],
            count=1, dtype="uint8",
            crs=RioCRS.from_epsg(4326),
            transform=transform,
            nodata=255,
        ) as dst:
            dst.write(mask_arr, 1)
            dst.set_band_description(1, "1=valid 0=cloud 255=nodata")
        try:
            total_mb += path_mask.stat().st_size / (1024 * 1024)
        except OSError:
            pass

        # ================================================================
        # ✅ FIX 1: POST-FILTRO CALIDAD — si TU PARCELA tiene >60% nubes/nodata,
        #          NO dejar 15 archivos negros en disco. Borra todo y marca too_cloudy.
        # ================================================================
        if local_pct > 60.0:
            # Limpiar carpeta (los 12 bandas + TrueColor + mask + metadata) para no dejar basura
            try:
                import shutil as _shutil2
                _shutil2.rmtree(sample_dir, ignore_errors=True)
                # Recrear directorio vacío por consistencia (aunque no sea estrictamente necesario)
                sample_dir.mkdir(parents=True, exist_ok=True)
                # Escribir mini explicación para TFG
                (sample_dir / "_SKIPPED_TOO_MUCH_CLOUDS.txt").write_text(
                    f"Esta muestra se descartó automáticamente.\n"
                    f"  Nubes ESCENA GLOBAL Sentinel-2 100km: {float(sample['scene_cloud_cover_pct']):.2f} %\n"
                    f"  Nubes EN TU PARCELA CONCRETA         : {local_pct:.2f} % (umbral permitido <60%)\n"
                    f"  product_id = {sample.get('product_id','')}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            logger.warning(
                "SKIP muestra %s por demasiadas nubes locales: %.1f%% (escena global %.1f%%)",
                crop_id, local_pct, float(sample["scene_cloud_cover_pct"]),
            )
            return DownloadResult(
                sample_folder=folder,
                crop_id=crop_id,
                status="too_cloudy",
                error=f"local_cloud={local_pct:.1f}% > 60% umbral permitido (escena {float(sample['scene_cloud_cover_pct']):.1f}%)",
                cloud_local_pct=round(float(local_pct), 3),
            )

        # 5) metadata.json: ahora image_path = lista de bandas individuales
        band_names_full = [p.name for p in band_paths]
        if true_color_path.exists():
            band_names_full.insert(0, true_color_path.name)
        meta = ImageMetadata(
            crop_id=crop_id,
            crop_type=sample["crop_type"],
            class_name=sample["class_name"],
            class_value=int(sample["class"]),
            area_ha=round(float(sample["area_ha"]), 4),
            date=sample["acquisition_date"],
            year=int(sample["year"]),
            month=int(sample["month"]),
            scene_cloud_cover=round(float(sample["scene_cloud_cover_pct"]), 3),
            local_cloud_cover_pct=round(float(local_pct), 3),
            resolution=int(cfg.sentinel.resolution),
            crs="EPSG:4326",
            bbox=[round(x, 6) for x in list(bbox)],
            source_collection=cfg.sentinel.collection,
            sentinel_product_id=str(sample.get("product_id") or ""),
            bands=list(L2A_BANDS),
            image_path="; ".join(band_names_full),
            cloud_mask_path="cloud_mask.tif",
            status="ok",
        )
        save_image_metadata(meta, meta_json)

        # Referencia a B04 como principal para el checkpoint
        path_primary = band_paths[idx_r] if band_paths else (sample_dir / "A_B04_(Raw).tiff")
        return DownloadResult(
            sample_folder=folder,
            crop_id=crop_id,
            status="ok",
            error=None,
            path_12bands=str(path_primary),
            path_mask=str(path_mask),
            path_meta=str(meta_json),
            mb_12bands=round(total_mb, 2),
            cloud_local_pct=round(float(local_pct), 3),
        )

    except Exception as exc:
        logger.exception("FALLÓ muestra %s/%s : %s", crop_id, folder, str(exc)[:200])
        try:
            (sample_dir / "_error.txt").write_text(str(exc), encoding="utf-8")
        except Exception:
            pass
        return DownloadResult(
            sample_folder=folder,
            crop_id=crop_id,
            status="error",
            error=str(exc)[:300],
        )


# ---- Entry mass workflow --------------------------------------------------
def run_mass_download(
    cfg_path: str | None = None,
    max_parcels: int | None = None,
    max_workers: int = 3,
    assume_yes: bool = False,
    overwrite: bool = False,
    output_root: Path | None = None,
    from_estimate_csv: Path | None = None,
) -> int:
    cfg = load_config(cfg_path)

    if output_root is None:
        # Año desde config
        yyyy = str(cfg.temporal.start_date)[:4]
        output_root = PROJECT_ROOT / "data" / f"mass_dataset_palma_{yyyy}"
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    aoi_gdf = repair_geometries(load_aoi_gdf(cfg.palm.output_aoi_abs))

    # Decidir cuantas parcelas
    if max_parcels is None and cfg.test_mode:
        max_parcels = 10
    if max_parcels is not None and max_parcels < len(aoi_gdf):
        top = aoi_gdf.sort_values("area_ha", ascending=False).head(max_parcels).reset_index(drop=True).copy()
    else:
        top = aoi_gdf.reset_index(drop=True).copy()

    # -------------------------------------------------------
    # PASO 1/3: Construir catálogo (vía CSV bypass O Catalog API)
    # -------------------------------------------------------
    samples: list[dict[str, Any]] = []
    samples_source_label = "CAT"
    if from_estimate_csv is not None:
        samples_source_label = "CSV"
        logger.info("PASO 1/3: Construyendo catálogo desde CSV estimate_report_monthly.csv (sin Catalog API)...")
        from_estimate_csv = Path(from_estimate_csv).resolve()
        if not from_estimate_csv.exists():
            raise FileNotFoundError(f"No existe CSV estimate: {from_estimate_csv}")
        top_ids = set(top["crop_id"].astype(str).tolist())
        parcel_by_id: dict[str, Any] = {}
        for _, r in top.iterrows():
            parcel_by_id[str(r["crop_id"])] = r

        def _parse_time_from_product(pid: str) -> str:
            parts = str(pid).split("_")
            for p in parts:
                if len(p) == 15 and p[8] == "T":
                    return p[9:15]
            return "153126"

        rows_in = 0
        with open(from_estimate_csv, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows_in += 1
                if str(row.get("status", "")) != "available":
                    continue
                cid = str(row["crop_id"])
                if cid not in parcel_by_id:
                    continue
                parcel = parcel_by_id[cid]
                best_date = str(row["best_date"]).strip()
                best_pid = str(row["best_product_id"]).strip()
                cloud_raw = row.get("best_cloud", "")
                try:
                    cloud = float(cloud_raw) if cloud_raw else 0.0
                except (TypeError, ValueError):
                    cloud = 0.0
                bbox = tuple(get_bbox_wgs84(parcel.geometry))
                yy = int(row["year"]); mm = int(row["month"])
                acq_date = best_date if len(best_date) == 10 else f"{yy:04d}-{mm:02d}-15"
                time_str = _parse_time_from_product(best_pid)
                samples.append({
                    "crop_id": cid,
                    "crop_type": "oil_palm",
                    "class": int(parcel["class"]),
                    "class_value": int(parcel["class"]),
                    "class_name": str(parcel.get("class_name") or ("Industrial" if int(parcel["class"]) == 1 else "Smallholder")),
                    "area_ha": float(parcel["area_ha"]),
                    "year": int(yy),
                    "month": int(mm),
                    "acquisition_date": acq_date,
                    "acquisition_time_str": time_str,
                    "acquisition_datetime_iso": f"{acq_date}T{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}Z",
                    "sentinel_product_id": best_pid,
                    "scene_cloud_cover_pct": round(cloud, 2),
                    "bbox_wgs84": list(bbox),
                    "geometry": parcel.geometry,
                    "product_id": best_pid,
                    "item_id": best_pid,
                })
        logger.info("  CSV leido: %s filas → %s muestras status=available en %d parcelas top.",
                    f"{rows_in:,}", f"{len(samples):,}", len(top_ids))
    else:
        samples_source_label = "CAT"
        logger.info("PASO 1/3: Construyendo catálogo de muestras vía Catalog API... (%d parcelas x %d meses = max %d)",
                    len(top),
                    len(_parse_start_end(cfg.temporal.start_date, cfg.temporal.end_date)),
                    len(top) * len(_parse_start_end(cfg.temporal.start_date, cfg.temporal.end_date)),
                    )
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="EstMass") as ex:
            futs = {}
            for i in range(len(top)):
                parcel = top.iloc[i:i + 1]
                cid = parcel.iloc[0]["crop_id"]
                futs[ex.submit(_samples_for_parcel, cfg, parcel)] = cid
            with tqdm.tqdm(total=len(futs), desc="Catalog", unit="parcela") as pbar:
                for fut in as_completed(futs):
                    cid = futs[fut]
                    try:
                        rows = fut.result()
                        samples.extend(rows)
                    except Exception as exc:
                        logger.warning("Catalog %s EXC: %s", cid, str(exc)[:120])
                    pbar.update(1)

    # Deduplicar por (crop_id, product_id):
    seen: set[tuple[str, str]] = set()
    uniq: list[dict[str, Any]] = []
    for s in samples:
        k = (str(s["crop_id"]), str(s["product_id"]))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)
    samples = uniq
    logger.info("Fuente %s: %d muestras únicas (disponibles).", samples_source_label, len(samples))

    # Ya descargadas: reconoce tanto legacy 12bands.tif como nuevo formato A_B04_(Raw).tiff
    n_exists = 0
    for s in samples:
        fol = _sample_folder_name(
            s["acquisition_date"], s["acquisition_time_str"], tuple(float(x) for x in s["bbox_wgs84"])
        )
        d = output_root / fol
        if (d / "metadata.json").exists() and ((d / "A_B04_(Raw).tiff").exists() or (d / "12bands.tif").exists()):
            n_exists += 1
    n_to_do = len(samples) - n_exists

    # Estimación:
    mb_avg = 45.0  # por muestra (12 bandas individuales float32 + True Color uint8 + mask)
    gb_est = n_to_do * mb_avg / 1024.0
    sec_per_sample = 12.0  # promedio de PALMA_0001
    est_hours = (n_to_do * sec_per_sample) / (3600.0 * max(1, max_workers))

    print()
    print("=" * 88)
    print("  RESUMEN ANTES DE DESCARGA MASIVA")
    print("=" * 88)
    print(f"  Output root                  : {output_root}")
    print(f"  Formato entrega              : 12 TIFFs individuales + A_True_Color.tiff + cloud_mask.tif + metadata.json")
    print(f"  Parcelas seleccionadas       : {len(top):,}  (de {len(aoi_gdf):,} totales)")
    print(f"  Periodo                      : {cfg.temporal.start_date} -> {cfg.temporal.end_date}")
    print(f"  Muestras disponibles ({samples_source_label})   : {len(samples):,}")
    print(f"    - Ya descargadas (skip)    : {n_exists:,}")
    print(f"    - NUEVAS por descargar     : {n_to_do:,}")
    print(f"  Tamaño estimado (12 bandas ind. + TrueColor): {gb_est:.1f} GB")
    print(f"  Duración ~estimada           : {est_hours:.1f} h  (workers={max_workers}, ~{sec_per_sample:.0f}s/muestra)")
    print(f"  Máx. cloud cover (scene)     : {cfg.sentinel.max_cloud_cover}%")
    print(f"  Resolución                   : {cfg.sentinel.resolution} m")
    print(f"  Bandas L2A (12)              : {', '.join(L2A_BANDS)}")
    print("=" * 88)

    if n_to_do == 0:
        logger.info("No hay muestras nuevas por descargar. Reportando final.")
    elif not assume_yes:
        try:
            ans = input(f"Continuar descarga MASIVA de {n_to_do:,} muestras nuevas [s/N]: ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in {"s", "si", "y", "yes"}:
            logger.info("Cancelado por el usuario.")
            return 2

    # -------------------------------------------------------
    # PASO 2/3: Descarga con workers y checkpoint
    # -------------------------------------------------------
    checkpoint = output_root / "checkpoint_download.csv"
    csv_fields = [f.name for f in DownloadResult.__dataclass_fields__.values()]
    results: list[DownloadResult] = []

    def _save_result(r: DownloadResult):
        exists = checkpoint.exists()
        with open(checkpoint, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=csv_fields)
            if not exists:
                w.writeheader()
            w.writerow(asdict(r))

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="MassDL") as ex:
        futs = {}
        for s in samples:
            fol = _sample_folder_name(
                s["acquisition_date"], s["acquisition_time_str"], tuple(float(x) for x in s["bbox_wgs84"])
            )
            meta_p = output_root / fol / "metadata.json"
            b04_p = output_root / fol / "A_B04_(Raw).tiff"
            if (meta_p.exists() and b04_p.exists()) and not overwrite:
                r = DownloadResult(
                    sample_folder=fol,
                    crop_id=str(s["crop_id"]),
                    status="skip_exists",
                    path_12bands=str(b04_p),
                    path_mask=str(output_root / fol / "cloud_mask.tif"),
                    path_meta=str(meta_p),
                )
                results.append(r)
                continue
            # También skipear si se marcó previamente como too_cloudy (re-run no las baja de nuevo)
            skipped_txt = output_root / fol / "_SKIPPED_TOO_MUCH_CLOUDS.txt"
            if skipped_txt.exists() and not overwrite:
                try:
                    cc_line = [ln for ln in skipped_txt.read_text(encoding="utf-8").splitlines() if "TU PARCELA" in ln][0]
                    cc_pct = float(cc_line.split(":")[1].split(" %")[0].strip()) if ":" in cc_line else 99.0
                except Exception:
                    cc_pct = 99.0
                r = DownloadResult(
                    sample_folder=fol,
                    crop_id=str(s["crop_id"]),
                    status="too_cloudy",
                    error="Descartada en ejecución previa (demasiadas nubes locales)",
                    cloud_local_pct=round(cc_pct, 3),
                )
                results.append(r)
                continue
            futs[ex.submit(_download_sample, cfg, s, output_root, overwrite)] = fol

        with tqdm.tqdm(total=len(futs), desc="Descarga", unit="muestra") as pbar:
            for fut in as_completed(futs):
                try:
                    r = fut.result()
                except Exception as exc:
                    fol = futs[fut]
                    logger.error("Fallo descarga %s: %s", fol, str(exc)[:120])
                    r = DownloadResult(sample_folder=fol, crop_id="?", status="error", error=str(exc)[:300])
                results.append(r)
                if r.status != "skip_exists":
                    _save_result(r)
                pbar.update(1)

    # -------------------------------------------------------
    # PASO 3/3: Report final
    # -------------------------------------------------------
    report = output_root / "mass_dataset_report.csv"
    with open(report, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields)
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))

    n_ok = sum(1 for r in results if r.status == "ok")
    n_sk = sum(1 for r in results if r.status == "skip_exists")
    n_er = sum(1 for r in results if r.status == "error")
    n_tc = sum(1 for r in results if r.status == "too_cloudy")
    total_mb = sum(r.mb_12bands or 0.0 for r in results if r.status == "ok")
    # Tasa real
    total_valid = n_ok + n_tc
    yield_pct = (n_ok / total_valid * 100) if total_valid > 0 else 0
    print()
    print("=" * 88)
    print(f"  FINALIZADO. OK={n_ok:,}  (calidad parcela <60% nubes)  |  SKIP(existe)={n_sk:,}  |  ERROR={n_er:,}  |  TOO_CLOUDY descartadas={n_tc:,}")
    if total_valid:
        print(f"  YIELD UTIL REAL            : {yield_pct:.1f}%  ({n_ok:,} / {total_valid:,} intentos descarga)")
    print(f"  Tamaño OK 13 archivos/mues : {total_mb / 1024:.2f} GB")
    print(f"  Umbral nubes PARCELA       : < 60% (post-filtro local - garantiza imágenes NO negras)")
    print(f"  Umbral nubes ESCENA GLOBAL : < {cfg.sentinel.max_cloud_cover}% (maxCC)")
    print(f"  Report CSV                : {report}")
    print(f"  Checkpoint CSV            : {checkpoint}")
    print(f"  Output (explorar)         : {output_root}")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cfg", nargs="?", default=None)
    parser.add_argument("--max-parcels", type=int, default=None)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--output-root", type=str, default=None)
    parser.add_argument("--from-estimate-csv", type=str, default=None,
                        help="Path a estimate_report_monthly.csv (bypass Catalog API, usa datos ya guardados)")
    args = parser.parse_args()
    out_root = Path(args.output_root).resolve() if args.output_root else None
    csv_path = Path(args.from_estimate_csv).resolve() if args.from_estimate_csv else None
    raise SystemExit(run_mass_download(
        cfg_path=args.cfg,
        max_parcels=args.max_parcels,
        max_workers=args.workers,
        assume_yes=args.yes,
        overwrite=args.overwrite,
        output_root=out_root,
        from_estimate_csv=csv_path,
    ))
