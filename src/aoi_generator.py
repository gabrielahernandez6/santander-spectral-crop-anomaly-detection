"""
aoi_generator.py
================
Utilidades para trabajar con el GeoJSON de palma de aceite (palma_santander.geojson).
Permite cargar, validar, reparar geometrías, extraer bboxes y geometrías individuales
para enviar al Catalog y Process API.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import geopandas as gpd
from shapely.geometry import box, mapping
from shapely.validation import make_valid

from .config import AppConfig


logger = logging.getLogger(__name__)


def load_aoi_gdf(aoi_path: str | Path) -> gpd.GeoDataFrame:
    """Carga el GeoJSON de AOIs y valida estructura mínima."""
    aoi_path = Path(aoi_path)
    if not aoi_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de AOIs: {aoi_path}. "
            "Ejecuta primero la detección de palma (palm_detector.run_detection)."
        )

    gdf = gpd.read_file(aoi_path)
    if gdf.empty:
        raise ValueError(f"El archivo {aoi_path} no tiene polígonos.")

    required = {"crop_id", "geometry"}
    missing = required - set(gdf.columns)
    if missing:
        raise ValueError(
            f"El GeoJSON de AOI le faltan columnas obligatorias: {sorted(missing)}. "
            f"Columnas actuales: {sorted(gdf.columns)}"
        )

    if gdf.crs is None:
        raise ValueError(f"El GeoJSON {aoi_path} no tiene CRS definido.")
    if not gdf.crs.equals(gpd.GeoDataFrame(geometry=[], crs="EPSG:4326").crs):
        logger.info("Reproyectando AOI de %s a EPSG:4326", gdf.crs)
        gdf = gdf.to_crs(epsg=4326)

    return gdf


def repair_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Intenta reparar geometrías inválidas. Devuelve copia con geometry corregida."""
    gdf = gdf.copy()
    invalid_mask = ~gdf.geometry.is_valid
    if invalid_mask.any():
        n = int(invalid_mask.sum())
        logger.warning("Se encontraron %d geometrías inválidas. Reparando...", n)
        gdf.loc[invalid_mask, "geometry"] = gdf.loc[invalid_mask, "geometry"].apply(
            make_valid
        )
        still_invalid = ~gdf.geometry.is_valid
        if still_invalid.any():
            bad_ids = gdf.loc[still_invalid, "crop_id"].tolist()
            raise RuntimeError(
                f"No se pudieron reparar {int(still_invalid.sum())} geometrías: {bad_ids}"
            )
    return gdf


def get_bbox_wgs84(geometry) -> tuple[float, float, float, float]:
    """Devuelve (minx, miny, maxx, maxy) en WGS84 grados."""
    bounds = geometry.bounds
    return (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))


def get_geometry_as_geojson(geometry) -> dict:
    """Devuelve la geometría serializada como dict GeoJSON (para Catalog/Process)."""
    return mapping(geometry)


def subset_for_test_mode(
    gdf: gpd.GeoDataFrame,
    test_mode: bool,
    n_parcels: int = 1,
) -> gpd.GeoDataFrame:
    """Si test_mode está activado, devuelve solo las primeras N parcelas (por área)."""
    if not test_mode:
        return gdf.copy()
    subset = gdf.sort_values("area_ha", ascending=False).head(n_parcels).copy()
    logger.info(
        "[TEST_MODE] Seleccionando %d parcela(s) de prueba: %s",
        len(subset),
        subset["crop_id"].tolist(),
    )
    return subset


def parcel_iterator(
    cfg: AppConfig,
    aoi_gdf: gpd.GeoDataFrame | None = None,
) -> Iterable[gpd.GeoDataFrame]:
    """Itera sobre las parcelas, una a una (como GeoDataFrame de 1 fila),
    aplicando test_mode si corresponde.
    """
    if aoi_gdf is None:
        aoi_gdf = load_aoi_gdf(cfg.palm.output_aoi_abs)
    aoi_gdf = repair_geometries(aoi_gdf)
    aoi_gdf = subset_for_test_mode(aoi_gdf, test_mode=cfg.test_mode)
    for idx in range(len(aoi_gdf)):
        yield aoi_gdf.iloc[[idx]].copy()


def summarize_aoi(gdf: gpd.GeoDataFrame) -> dict:
    """Métricas rápidas del AOI."""
    total_area = float(gdf["area_ha"].sum()) if "area_ha" in gdf.columns else float("nan")
    return {
        "n_parcels": int(len(gdf)),
        "total_area_ha": round(total_area, 2),
        "classes": sorted(gdf["class"].unique().tolist()) if "class" in gdf.columns else [],
        "crs": str(gdf.crs),
        "bbox_total": list(gdf.total_bounds.tolist()),
    }
