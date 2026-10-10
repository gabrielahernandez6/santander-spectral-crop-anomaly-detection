"""
metadata.py
===========
Genera metadata JSON/CSV para cada muestra y reportes agregados.

Por cada imagen generada, el JSON de metadata incluye:
  - crop_id, crop_type, class (1/2)
  - date, year, month
  - cloud_cover (escena y local según máscara)
  - resolution, crs, bbox
  - source_collection, sentinel_product_id
  - bands (12 L2A)
  - image_path, cloud_mask_path
  - status: available | unavailable | error
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import geopandas as gpd
import rasterio

from .config import AppConfig
from .aoi_generator import get_bbox_wgs84
from .cloud_mask import (
    CLOUD_MASK_INVALID,
    CLOUD_MASK_NODATA,
    compute_pixel_cloud_cover_from_mask,
    read_cloud_mask,
)


logger = logging.getLogger(__name__)


@dataclass
class ImageMetadata:
    crop_id: str
    crop_type: str
    class_name: Optional[str] = None
    class_value: Optional[int] = None
    area_ha: Optional[float] = None
    date: Optional[str] = None
    year: Optional[int] = None
    month: Optional[int] = None
    scene_cloud_cover: Optional[float] = None
    local_cloud_cover_pct: Optional[float] = None
    resolution: Optional[int] = None
    crs: Optional[str] = None
    bbox: list[float] = field(default_factory=list)
    source_collection: Optional[str] = None
    sentinel_product_id: Optional[str] = None
    bands: list[str] = field(default_factory=list)
    image_path: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_dtype: Optional[str] = None
    cloud_mask_path: Optional[str] = None
    status: str = "available"
    error: Optional[str] = None
    notes: Optional[str] = None


def _relative_to_project(path: Optional[str | Path], project_root: Path) -> Optional[str]:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(project_root.resolve()))
    except Exception:
        return str(Path(path))


def populate_from_image(
    meta: ImageMetadata,
    image_path: Optional[Path],
    cloud_mask_path: Optional[Path],
    project_root: Path,
) -> ImageMetadata:
    if image_path and image_path.exists():
        try:
            with rasterio.open(image_path) as src:
                if meta.resolution is None and src.res is not None:
                    try:
                        res_x = float(src.res[0])
                        if abs(res_x) < 1:
                            meta.resolution = int(round(res_x / 9.0e-6))
                        else:
                            meta.resolution = int(round(res_x))
                    except Exception:
                        pass
                if meta.crs is None:
                    meta.crs = str(src.crs) if src.crs else None
                meta.image_width = int(src.width)
                meta.image_height = int(src.height)
                meta.image_dtype = str(src.dtypes[0]) if src.dtypes else None
                if not meta.bands:
                    meta.bands = [desc or f"B{i+1:02d}" for i, desc in enumerate(src.descriptions)]
                if not meta.bbox and src.bounds is not None:
                    meta.bbox = [
                        float(src.bounds.left),
                        float(src.bounds.bottom),
                        float(src.bounds.right),
                        float(src.bounds.top),
                    ]
            meta.image_path = _relative_to_project(image_path, project_root)
        except rasterio.RasterIOError as e:
            logger.warning("No se pudo leer metadata de %s: %s", image_path, e)
            meta.status = "error"
            meta.error = f"RasterIOError: {e}"

    if cloud_mask_path and cloud_mask_path.exists():
        try:
            mask = read_cloud_mask(cloud_mask_path)
            meta.local_cloud_cover_pct = compute_pixel_cloud_cover_from_mask(mask)
            meta.cloud_mask_path = _relative_to_project(cloud_mask_path, project_root)
        except Exception as e:
            logger.warning("No se pudo leer cloud mask %s: %s", cloud_mask_path, e)
    return meta


def build_metadata_record(
    cfg: AppConfig,
    *,
    parcel_row: Any,
    monthly_selection: Any,  # MonthlySelection
    image_path: Optional[Path],
    cloud_mask_path: Optional[Path],
) -> ImageMetadata:
    gdf_row = parcel_row.iloc[0] if hasattr(parcel_row, "iloc") else parcel_row
    meta = ImageMetadata(
        crop_id=str(monthly_selection.crop_id),
        crop_type=str(getattr(gdf_row, "crop_type", "oil_palm")),
        class_name=str(getattr(gdf_row, "class_name", None)),
        class_value=int(getattr(gdf_row, "class", 0)) if hasattr(gdf_row, "class") else None,
        area_ha=float(getattr(gdf_row, "area_ha", 0.0)) if hasattr(gdf_row, "area_ha") else None,
        date=str(monthly_selection.acquisition_date) if monthly_selection.acquisition_date else None,
        year=int(monthly_selection.year),
        month=int(monthly_selection.month),
        scene_cloud_cover=float(monthly_selection.cloud_cover) if monthly_selection.cloud_cover is not None else None,
        source_collection=cfg.sentinel.collection,
        sentinel_product_id=str(monthly_selection.product_id) if monthly_selection.product_id else None,
        bands=list(cfg.sentinel.bands),
        resolution=int(cfg.sentinel.resolution),
        bbox=list(get_bbox_wgs84(gdf_row.geometry)),
        status=str(monthly_selection.status),
    )
    if monthly_selection.status != "available":
        meta.notes = "monthly_selection.status=unavailable"
        return meta

    meta = populate_from_image(meta, image_path, cloud_mask_path, PROJECT_ROOT)
    return meta


# project root reference (relative paths)
from .config import PROJECT_ROOT  # noqa: E402


def save_image_metadata(meta: ImageMetadata, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(meta), f, ensure_ascii=False, indent=2, default=str)
    logger.debug("Metadata guardada: %s", out_path)
    return out_path


def save_dataset_summary_csv(
    records: Iterable[ImageMetadata],
    out_path: str | Path,
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in records]
    if not rows:
        logger.warning("No hay records para escribir CSV de resumen.")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("")
        return out_path
    fieldnames = list(rows[0].keys())
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Resumen CSV guardado en %s (%d registros)", out_path, len(rows))
    return out_path
