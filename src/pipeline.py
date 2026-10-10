"""
pipeline.py
===========
Coordina TODO el flujo end-to-end:

 [1/6] Detectar palma -> palm_santander.geojson
 [2/6] Generar AOIs (leer y validar geometrías)
 [3/6] Consultar Catalog API
 [4/6] Selección mensual
 [5/6] Descargar bandas via Process API
 [6/6] Preprocessing + metadata

Logging con mensajes: [1/6], [2/6], ...
TEST_MODE = true solo procesa 1 parcela x 1 mes x 1 imagen.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Iterable

import geopandas as gpd

from .config import AppConfig, load_config
from .palm_detector import run_detection, summarize_polygons
from .aoi_generator import (
    load_aoi_gdf,
    repair_geometries,
    parcel_iterator,
    summarize_aoi,
)
from .image_selector import (
    save_selections_report,
    select_monthly_for_parcel,
)
from .downloader import download_monthly_image
from .preprocessing import ensure_uniform_image, validate_target_image
from .metadata import (
    ImageMetadata,
    build_metadata_record,
    save_dataset_summary_csv,
    save_image_metadata,
)
from estimate_dataset import estimate_full as estimate_dataset_full  # noqa: F401


logger = logging.getLogger(__name__)


STEPS_TOTAL = 6


def _confirm(msg: str) -> bool:
    try:
        resp = input(f"{msg} [s/N]: ").strip().lower()
    except EOFError:
        return False
    return resp in {"s", "si", "y", "yes"}


def _print_header(cfg: AppConfig, aoi_gdf: gpd.GeoDataFrame) -> None:
    aoi_stats = summarize_aoi(aoi_gdf)
    print()
    print("=" * 72)
    print("  PIPELINE TFG - PALMA DE ACEITE SANTANDER x SENTINEL-2 L2A")
    print("=" * 72)
    print(f"  Modo de ejecución : {'TEST' if cfg.test_mode else 'PRODUCCIÓN (TODAS LAS PARCELAS)'}")
    print(f"  Zona de estudio    : {cfg.study_area.name}, {cfg.study_area.country}")
    print(f"  Parcelas detectadas: {aoi_stats['n_parcels']}")
    print(f"  Área total         : {aoi_stats['total_area_ha']:,.2f} ha")
    print(f"  Periodo temporal   : {cfg.temporal.start_date} a {cfg.temporal.end_date}")
    print(f"  Cantidad de meses  : {cfg.temporal.months}")
    print(f"  Colección Sentinel : {cfg.sentinel.collection}")
    print(f"  Resolución objetivo: {cfg.sentinel.resolution} m")
    print(f"  Bandas ({len(cfg.sentinel.bands)}) : {', '.join(cfg.sentinel.bands)}")
    print(f"  Máx. cloud cover   : {cfg.sentinel.max_cloud_cover}%")
    print("=" * 72)
    print()


# ---------------------------------------------------------------------------
# Step 1-2: Detección y carga de AOIs
# ---------------------------------------------------------------------------
def step_detect_palm(cfg: AppConfig) -> gpd.GeoDataFrame:
    logger.info("[1/%d] Detectando palma en Santander (clases %s)...",
                STEPS_TOTAL, cfg.palm.classes)
    if cfg.palm.output_aoi_abs.exists() and cfg.test_mode:
        logger.info("  Reutilizando AOI existente %s (test_mode)", cfg.palm.output_aoi_abs)
        gdf = load_aoi_gdf(cfg.palm.output_aoi_abs)
    else:
        gdf = run_detection(cfg)
    logger.info("  Resumen:\n%s", summarize_polygons(gdf).to_string())
    return gdf


def step_prepare_aoi(cfg: AppConfig, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    logger.info("[2/%d] Preparando AOI (reparar geometrías, aplicar test_mode si aplica)",
                STEPS_TOTAL)
    gdf = repair_geometries(gdf)
    if cfg.test_mode:
        from .aoi_generator import subset_for_test_mode
        gdf = subset_for_test_mode(gdf, test_mode=True, n_parcels=1)
        # si además queremos 1 solo mes, lo gestionamos en el selector (haciendo un slice)
    logger.info("  Listo para procesar %d parcela(s).", len(gdf))
    return gdf


# ---------------------------------------------------------------------------
# Steps 3-6: Por parcela -> Catalog -> selección mensual -> descarga -> preproc -> metadata
# ---------------------------------------------------------------------------
def process_parcel(
    cfg: AppConfig,
    parcel_row_gdf: gpd.GeoDataFrame,
) -> list[ImageMetadata]:
    row = parcel_row_gdf.iloc[0]
    crop_id = str(row["crop_id"])
    logger.info("-" * 72)
    logger.info("Procesando parcela: %s (%.2f ha, %s)",
                crop_id, float(row["area_ha"]), str(row["class_name"]))

    # [3/6] Catalog + [4/6] Selección mensual
    logger.info("[3+4/%d] Consultando Catalog API y seleccionando MEJOR imagen por mes...",
                STEPS_TOTAL)
    selections = select_monthly_for_parcel(cfg, parcel_row=row)

    # En test mode, solo procesamos 1 mes (el primer available, o el primero si no hay)
    if cfg.test_mode:
        available = [s for s in selections if s.status == "available"]
        if available:
            selections = [available[0]]
        else:
            selections = selections[:1]
        logger.info("  [TEST_MODE] Limitando selección mensual a 1 mes: %04d-%02d (%s)",
                    selections[0].year, selections[0].month, selections[0].status)

    report_dir = cfg.output.crop_dir_abs / crop_id
    report_dir.mkdir(parents=True, exist_ok=True)
    save_selections_report(selections, report_dir / "selections.json")

    records: list[ImageMetadata] = []

    for sel_idx, selection in enumerate(selections, start=1):
        logger.info(
            "  [%d/%d] Mes %04d-%02d -> %s",
            sel_idx, len(selections), selection.year, selection.month, selection.status,
        )

        image_path: Path | None = None
        cloud_mask_path: Path | None = None

        if selection.status == "available":
            # [5/6] Descarga
            logger.info("  [5/%d] Descargando bandas via Process API...", STEPS_TOTAL)
            try:
                image_path, cloud_mask_path = download_monthly_image(
                    cfg, parcel_row=row, selection=selection,
                )
            except Exception as e:
                logger.exception("Fallo en descarga: %s", e)
                selection.status = "error"
                meta = build_metadata_record(cfg, parcel_row=parcel_row_gdf,
                                             monthly_selection=selection,
                                             image_path=None, cloud_mask_path=None)
                meta.status = "error"
                meta.error = str(e)
                records.append(meta)
                continue

            # [6/6] Preprocessing
            if image_path is not None:
                logger.info("  [6/%d] Preprocessing (res=%dm, CRS WGS84, 12 bandas)",
                            STEPS_TOTAL, cfg.sentinel.resolution)
                try:
                    image_path = ensure_uniform_image(
                        image_path, image_path,
                        target_resolution_m=int(cfg.sentinel.resolution),
                        expected_bands=cfg.sentinel.bands,
                    )
                    validate_target_image(image_path, cfg.sentinel.bands)
                except Exception as e:
                    logger.exception("Fallo en preprocessing: %s", e)
                    selection.status = "error"

        # Metadata siempre (aunque status unavailable/error)
        meta = build_metadata_record(
            cfg,
            parcel_row=parcel_row_gdf,
            monthly_selection=selection,
            image_path=image_path,
            cloud_mask_path=cloud_mask_path,
        )
        if image_path is not None:
            save_image_metadata(meta, report_dir / f"{selection.year:04d}-{selection.month:02d}_metadata.json")
        records.append(meta)

    logger.info("Parcela %s terminada. %d registros (status available=%d).",
                crop_id,
                len(records),
                sum(1 for r in records if r.status == "available"))
    return records


def run_pipeline(config_path: str | Path | None = None) -> int:
    cfg = load_config(config_path)

    # Step 1: detectar palma (o reutilizar AOI si existe + test)
    aoi_gdf = step_detect_palm(cfg)
    aoi_gdf = step_prepare_aoi(cfg, aoi_gdf)

    # Mostrar resumen
    _print_header(cfg, aoi_gdf)

    # Confirmación si NO estamos en test mode
    if not cfg.test_mode:
        logger.warning(
            "MODO PRODUCCIÓN: Se intentarán procesar %d parcelas x %d meses.",
            len(aoi_gdf), cfg.temporal.months,
        )
        if not _confirm("¿Continuar con la descarga masiva?"):
            logger.info("Cancelado por el usuario.")
            return 2

    t0 = time.time()
    all_records: list[ImageMetadata] = []
    for idx, parcel in enumerate(parcel_iterator(cfg, aoi_gdf=aoi_gdf), start=1):
        logger.info("=" * 72)
        logger.info("PARCELA %d/%d", idx, len(aoi_gdf))
        try:
            records = process_parcel(cfg, parcel)
            all_records.extend(records)
        except Exception as e:
            logger.exception("Error fatal procesando parcela %d: %s", idx, e)
            continue

    # CSV resumen global
    if all_records:
        csv_path = cfg.output.crop_dir_abs / "dataset_summary.csv"
        save_dataset_summary_csv(all_records, csv_path)

    elapsed = time.time() - t0
    logger.info("Pipeline COMPLETADO en %.1fs. Total registros: %d", elapsed, len(all_records))
    available = sum(1 for r in all_records if r.status == "available")
    unavailable = sum(1 for r in all_records if r.status == "unavailable")
    errors = sum(1 for r in all_records if r.status == "error")
    logger.info(
        "  STATUS: available=%d | unavailable=%d | error=%d",
        available, unavailable, errors,
    )
    return 0
