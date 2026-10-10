"""
palm_detector.py
================
Detección automática de zonas de palma de aceite en Santander a partir del
dataset Global Oil Palm Extent (609 teselas GeoTIFF a 10 m).

Flujo:
  1. Leer límite de Santander (GeoJSON)
  2. Encontrar qué teselas TIFF intersectan el límite
  3. Recortar + filtrar clases 1 y 2 (industrial / pequeños productores)
  4. Agrupar píxeles contiguos por label de componente conectado
  5. Polygonize, calcular área (ha), filtrar < min_area
  6. Asignar IDs PALMA_####
  7. Guardar palma_santander.geojson en EPSG:4326
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from rasterio.io import DatasetReader
from rasterio.mask import mask as rio_mask
from scipy import ndimage
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.ops import unary_union
from pyproj import CRS

from .config import AppConfig


logger = logging.getLogger(__name__)


# =========================================================================
# Helpers
# =========================================================================
def _validate_boundary(boundary_path: Path) -> gpd.GeoDataFrame:
    """Carga y valida el límite geográfico. Devuelve GeoDataFrame en EPSG:4326."""
    if not boundary_path.exists():
        raise FileNotFoundError(
            "No se encontró el límite geográfico de Santander. "
            f"Se esperaba el archivo en: {boundary_path}\n"
            "Formato requerido: GeoJSON con la geometría del departamento, "
            "idealmente en WGS84 (EPSG:4326) o cualquier CRS reproyectable."
        )

    logger.info("Leyendo límite desde %s", boundary_path.name)
    gdf = gpd.read_file(boundary_path)

    if gdf.empty:
        raise ValueError(f"El archivo {boundary_path} no contiene geometrías.")

    if gdf.crs is None:
        raise ValueError(
            f"El límite {boundary_path} no tiene CRS definido. "
            "Define el CRS (preferible EPSG:4326) antes de continuar."
        )

    logger.info("Límite cargado: %d geometría(s) | CRS=%s", len(gdf), gdf.crs)

    if not gdf.crs.equals(CRS.from_epsg(4326)):
        logger.info("Reproyectando límite de %s a EPSG:4326", gdf.crs)
        gdf = gdf.to_crs(epsg=4326)

    # Disolver en caso de múltiples geometrías (municipios)
    if len(gdf) > 1:
        logger.info("Disolviendo %d geometrías en un único polígono de estudio", len(gdf))
        merged = gdf.dissolve()
        merged.crs = gdf.crs
        gdf = merged

    return gdf


def _find_tiles_intersecting(
    boundary_gdf: gpd.GeoDataFrame,
    palm_map_dir: Path,
) -> list[Path]:
    """Encuentra qué GeoTIFFs del dataset tienen intersección espacial con el límite."""
    if not palm_map_dir.exists():
        raise FileNotFoundError(
            f"No existe el directorio del mapa de palma: {palm_map_dir}"
        )

    tif_files = sorted(palm_map_dir.glob("*.tif"))
    if not tif_files:
        raise FileNotFoundError(
            f"No se encontraron archivos *.tif en {palm_map_dir}. "
            "Descomprime primero GlobalOilPalm_OP-extent.zip dentro de data/palm_map/."
        )

    logger.info(
        "Escaneando %d GeoTIFF para hallar intersección con Santander...",
        len(tif_files),
    )

    boundary_geom = boundary_gdf.unary_union
    intersecting: list[Path] = []

    for tif in tif_files:
        try:
            with rasterio.open(tif) as src:
                tile_bounds = src.bounds
                tile_poly = Polygon.from_bounds(*tile_bounds)
                if tile_poly.intersects(boundary_geom):
                    intersecting.append(tif)
        except rasterio.RasterIOError as e:
            logger.warning("No se pudo leer %s: %s. Saltando.", tif.name, e)

    logger.info(
        "Teselas que intersectan Santander: %d / %d", len(intersecting), len(tif_files)
    )
    for t in intersecting:
        logger.info("  -> %s", t.name)

    if not intersecting:
        raise RuntimeError(
            "Ninguna tesela del mapa de palma intersecta el límite de Santander. "
            "Revisa el CRS del límite o la ubicación de los TIFF."
        )
    return intersecting


def _clip_and_classify(
    src: DatasetReader,
    boundary_gdf: gpd.GeoDataFrame,
    valid_classes: Iterable[int],
) -> tuple[np.ndarray, dict]:
    """Recorta el raster al límite y devuelve únicamente los píxeles que
    pertenecen a las clases de palma válidas (resto = 0).

    Retorna (masked_array, transform_used).
    """
    shapes = [g.__geo_interface__ for g in boundary_gdf.geometry]
    try:
        clipped, transform = rio_mask(
            src, shapes, crop=True, nodata=0, filled=True, all_touched=False
        )
    except ValueError as e:
        logger.warning("Fallo al recortar raster %s: %s. Saltando.", src.name, e)
        return np.array([]), {}

    arr = clipped[0]  # primera banda
    valid_classes = set(int(c) for c in valid_classes)

    is_valid = np.isin(arr, list(valid_classes))
    out = np.where(is_valid, arr.astype(np.uint8), np.uint8(0))

    meta = {
        "transform": transform,
        "crs": src.crs,
        "width": out.shape[1],
        "height": out.shape[0],
    }
    logger.info(
        "  Recorte %s: %dx%d px, %.1f%% de píxeles de palma",
        Path(src.name).name,
        out.shape[1],
        out.shape[0],
        100 * (is_valid.sum() / max(1, is_valid.size)),
    )
    return out, meta


def _polygonize_connected_components(
    tile_data: np.ndarray,
    transform,
    valid_classes: set[int],
) -> list[dict]:
    """Para cada clase, separa en componentes conectados (8-connectivity) y
    devuelve una lista de polígonos con su clase original.

    Devuelve lista de diccionarios: [{"geometry": Polygon, "class": int}, ...]
    """
    results: list[dict] = []

    for klass in sorted(valid_classes):
        class_mask = (tile_data == klass).astype(np.uint8)
        if not np.any(class_mask):
            continue
        labeled, num_features = ndimage.label(class_mask, structure=np.ones((3, 3)))
        if num_features == 0:
            continue

        logger.info("    Clase %d: %d componente(s) conectado(s)", klass, num_features)

        # shapes() sobre el labeled completo en UNA sola pasada (O(1) raster reads)
        mask = labeled > 0
        for geom_dict, _label_val in features.shapes(
            labeled.astype(np.int32), mask=mask, transform=transform
        ):
            poly = shape(geom_dict)
            if poly.is_empty:
                continue
            poly = poly.buffer(0)
            if poly.is_empty:
                continue
            if isinstance(poly, MultiPolygon):
                for sub in poly.geoms:
                    if sub.area > 0:
                        results.append({"geometry": sub, "class": int(klass)})
            elif isinstance(poly, Polygon) and poly.area > 0:
                results.append({"geometry": poly, "class": int(klass)})

    return results


def _area_in_hectares(geometry, source_crs) -> float:
    """Calcula el área en hectáreas. Si el CRS es geográfico, reproyecta a UTM."""
    if source_crs is None:
        raise ValueError("No se puede calcular área sin CRS.")

    if source_crs.is_geographic:
        # Aproximar zona UTM basada en centroide
        geom_4326 = gpd.GeoSeries([geometry], crs=source_crs)
        centroid = geom_4326.iloc[0].centroid
        utm_zone = int((centroid.x + 180) // 6) + 1
        if centroid.y >= 0:
            utm_crs = CRS.from_epsg(32600 + utm_zone)
        else:
            utm_crs = CRS.from_epsg(32700 + utm_zone)
        area_m2 = geom_4326.to_crs(utm_crs).iloc[0].area
    else:
        area_m2 = geometry.area
    return area_m2 / 10000.0


# =========================================================================
# API pública
# =========================================================================
def detect_oil_palm(
    boundary_path: str | Path,
    palm_map_dir: str | Path,
    output_aoi_path: str | Path,
    valid_classes: list[int] | None = None,
    minimum_area_hectares: float = 0.5,
) -> gpd.GeoDataFrame:
    """Ejecuta la detección completa de palma de aceite.

    Args:
        boundary_path: Ruta al GeoJSON con el límite de Santander
        palm_map_dir: Directorio con los 609 GeoTIFF del dataset Global Oil Palm
        output_aoi_path: Ruta donde guardar palma_santander.geojson
        valid_classes: Clases raster a conservar (default [1, 2])
        minimum_area_hectares: Área mínima en hectáreas para conservar un polígono

    Returns:
        GeoDataFrame con los polígonos de palma (EPSG:4326), columnas:
            crop_id, crop_type, class, area_ha, geometry
    """
    if valid_classes is None:
        valid_classes = [1, 2]
    valid_classes_set = set(int(c) for c in valid_classes)

    boundary_path = Path(boundary_path)
    palm_map_dir = Path(palm_map_dir)
    output_aoi_path = Path(output_aoi_path)
    output_aoi_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Límite
    boundary_gdf = _validate_boundary(boundary_path)

    # 2. Teselas que intersectan
    tile_paths = _find_tiles_intersecting(boundary_gdf, palm_map_dir)

    # 3-5. Procesar cada tesela: recortar, clasificar, componentes, polygonize
    all_rows: list[dict] = []
    tile_crs = None

    for tif_path in tile_paths:
        logger.info("[%d/%d] Procesando %s", len(all_rows) + 1, len(tile_paths), tif_path.name)
        with rasterio.open(tif_path) as src:
            tile_crs = tile_crs or src.crs
            if tile_crs != src.crs:
                logger.warning(
                    "CRS inesperado en %s: %s vs %s. Reproyectando manualmente...",
                    tif_path.name, src.crs, tile_crs,
                )
            arr, meta = _clip_and_classify(src, boundary_gdf, valid_classes)
            if arr.size == 0:
                continue
            rows = _polygonize_connected_components(arr, meta["transform"], valid_classes_set)
            all_rows.extend(rows)

    if not all_rows:
        raise RuntimeError(
            "No se detectaron píxeles de palma dentro de Santander. "
            "Revisa las clases de interés o la calidad del límite."
        )

    logger.info("Total polígonos crudos (antes de filtro de área): %d", len(all_rows))

    # 6. Convertir a GeoDataFrame en EPSG:4326
    gdf = gpd.GeoDataFrame(all_rows, geometry="geometry", crs=tile_crs)
    if gdf.crs != CRS.from_epsg(4326):
        gdf = gdf.to_crs(epsg=4326)

    # 7. Calcular área en ha y filtrar
    logger.info("Calculando áreas y filtrando < %.2f ha", minimum_area_hectares)
    gdf["area_ha"] = gdf.geometry.apply(
        lambda g: _area_in_hectares(g, CRS.from_epsg(4326))
    )

    before = len(gdf)
    gdf = gdf[gdf["area_ha"] >= minimum_area_hectares].copy()
    logger.info("Filtrado: %d -> %d polígonos (%.2f ha mínima)", before, len(gdf), minimum_area_hectares)
    if gdf.empty:
        raise RuntimeError("Todos los polígonos fueron filtrados por área mínima.")

    # 8. Columnas semánticas y IDs
    gdf = gdf.sort_values("area_ha", ascending=False).reset_index(drop=True)
    gdf["crop_id"] = [f"PALMA_{i:04d}" for i in range(1, len(gdf) + 1)]
    gdf["crop_type"] = "oil_palm"
    gdf["class_name"] = gdf["class"].map({1: "industrial", 2: "smallholder"})

    # Columnas en orden amigable
    ordered_cols = ["crop_id", "crop_type", "class", "class_name", "area_ha", "geometry"]
    gdf = gdf[ordered_cols]

    # Conservar solo aquellos cuya geometría no es trivial
    gdf = gdf[gdf.geometry.area > 0].copy()

    # Orden final por área + reasignar IDs para que PALMA_0001 sea el más grande
    gdf = gdf.sort_values("area_ha", ascending=False).reset_index(drop=True)
    gdf["crop_id"] = [f"PALMA_{i:04d}" for i in range(1, len(gdf) + 1)]
    gdf = gdf[["crop_id", "crop_type", "class", "class_name", "area_ha", "geometry"]]

    # 9. Guardar
    logger.info("Guardando %d polígonos en %s", len(gdf), output_aoi_path)
    gdf.to_file(output_aoi_path, driver="GeoJSON", encoding="utf-8")

    return gdf


def summarize_polygons(gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """Devuelve una tabla resumen con estadísticas de los polígonos."""
    total_area_ha = gdf["area_ha"].sum()
    summary = (
        gdf.groupby("class_name")
        .agg(
            n_polygons=("crop_id", "count"),
            area_total_ha=("area_ha", "sum"),
            area_mean_ha=("area_ha", "mean"),
            area_min_ha=("area_ha", "min"),
            area_max_ha=("area_ha", "max"),
        )
        .round(2)
    )
    summary.loc["TOTAL"] = [
        len(gdf),
        round(total_area_ha, 2),
        round(gdf["area_ha"].mean(), 2),
        round(gdf["area_ha"].min(), 2),
        round(gdf["area_ha"].max(), 2),
    ]
    return summary


# =========================================================================
# Entry point que usa AppConfig
# =========================================================================
def run_detection(cfg: AppConfig) -> gpd.GeoDataFrame:
    return detect_oil_palm(
        boundary_path=cfg.study_area.boundary_abs,
        palm_map_dir=cfg.palm.map_dir_abs,
        output_aoi_path=cfg.palm.output_aoi_abs,
        valid_classes=cfg.palm.classes,
        minimum_area_hectares=cfg.palm.minimum_area_hectares,
    )
