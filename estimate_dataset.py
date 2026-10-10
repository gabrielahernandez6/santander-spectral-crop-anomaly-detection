"""
estimator.py
============
MODALIDAD: reporta disponibilidad SIN descargar imágenes.

Hace:
  2.434 AOI
      ↓
Catalog API (sentinel-2-l2a)
      ↓12 meses (o más: 24 / 36 configurable)
      ↓NO descarga Process API
      ↓Cuenta disponibles / unavailable por mes
      ↓Produce:
         • data/catalog/estimate_report_monthly.csv
         • data/catalog/estimate_report_parcels.csv
         • data/catalog/estimate_summary.json
         • Resumen por consola

Ejecutar (después de diagnosticar que Catalog funciona):

  python estimate_dataset.py
"""
from __future__ import annotations

import csv
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import tqdm  # barra de progreso robusta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ESTIMATOR")


PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import AppConfig, load_config  # noqa: E402
from src.aoi_generator import (  # noqa: E402
    load_aoi_gdf,
    repair_geometries,
    subset_for_test_mode,
    get_bbox_wgs84,
    parcel_iterator,
)
from src.catalog import search_sentinel  # noqa: E402
from src.image_selector import (  # noqa: E402
    _parse_start_end,
    _month_interval,
    _pick_best,
)


def estimate_parcel_months(
    cfg: AppConfig,
    parcel_row: gpd.GeoDataFrame,
) -> list[dict]:
    """Para 1 parcela, itera 12+ meses y consulta Catalog por mes.

    Retorna lista de dicts:
       {crop_id, year, month, candidates_count, best_cloud,
        best_date, best_product_id, status}
    """
    row = parcel_row.iloc[0]
    crop_id = str(row["crop_id"])
    bbox = list(get_bbox_wgs84(row.geometry))

    months = _parse_start_end(cfg.temporal.start_date, cfg.temporal.end_date)

    out: list[dict] = []
    for (y, m) in months:
        s, e = _month_interval(y, m)
        try:
            items = search_sentinel(
                cfg,
                bbox=bbox,
                start_date=s,
                end_date=e,
                max_pages=3,
            )
        except Exception as exc:
            logger.warning("%s %04d-%02d: Catalog error: %s", crop_id, y, m, exc)
            out.append({
                "crop_id": crop_id, "year": y, "month": m,
                "candidates_count": 0,
                "best_cloud": None,
                "best_date": None,
                "best_product_id": None,
                "status": "error",
                "error": str(exc)[:200],
            })
            continue

        best = _pick_best(items)
        if best is None:
            out.append({
                "crop_id": crop_id, "year": y, "month": m,
                "candidates_count": 0,
                "best_cloud": None,
                "best_date": None,
                "best_product_id": None,
                "status": "unavailable",
                "error": None,
            })
            continue

        out.append({
            "crop_id": crop_id, "year": y, "month": m,
            "candidates_count": len(items),
            "best_cloud": best.get("cloud_cover"),
            "best_date": str(best.get("datetime"))[:10] if best.get("datetime") else None,
            "best_product_id": str(best.get("product_id")) if best.get("product_id") else None,
            "status": "available",
            "error": None,
        })
    return out


def save_monthly_csv(records: Iterable[dict], out_path: Path) -> None:
    records = list(records)
    if not records:
        logger.warning("No records para monthly CSV.")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(records[0].keys())
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(records)
    logger.info("Monthly CSV guardado en %s (%d filas)", out_path, len(records))


def summarize_monthly(records: list[dict]) -> list[dict]:
    """Agrupa por (year,month) -> disponibles/unavailable/error."""
    grp = defaultdict(lambda: {"available": 0, "unavailable": 0, "error": 0,
                          "clouds": [], "total_candidates": 0})
    for r in records:
        key = (r["year"], r["month"])
        grp[key][r["status"]] = grp[key].get(r["status"], 0) + 1
        if r["best_cloud"] is not None:
            grp[key]["clouds"].append(float(r["best_cloud"]))
        grp[key]["total_candidates"] += int(r["candidates_count"] or 0)

    rows = []
    for (y, m), d in sorted(grp.items()):
        clouds = d["clouds"]
        mean = sum(clouds)/len(clouds) if clouds else None
        rows.append({
            "year": y, "month": m,
            "available": d["available"],
            "unavailable": d["unavailable"],
            "error": d["error"],
            "mean_best_cloud_pct": round(mean, 2) if mean is not None else None,
            "total_candidates_found": d["total_candidates"],
        })
    return rows


def save_parcel_availability(records: list[dict], gdf: gpd.GeoDataFrame, out_path: Path) -> None:
    """Disponibilidad por parcela (n_available_months / total_months)."""
    by_parcel = defaultdict(lambda: {"available": 0, "unavailable": 0, "error": 0,
                                "total_candidates": 0,
                                "clouds": []})
    for r in records:
        k = r["crop_id"]
        by_parcel[k][r["status"]] = by_parcel[k].get(r["status"], 0) + 1
        if r["best_cloud"] is not None:
            by_parcel[k]["clouds"].append(float(r["best_cloud"]))
        by_parcel[k]["total_candidates"] += int(r["candidates_count"] or 0)

    class_map = {row["crop_id"]: int(row["class"]) for _, row in gdf.iterrows()}
    class_name_map = {row["crop_id"]: str(row["class_name"]) for _, row in gdf.iterrows()}
    area_map = {row["crop_id"]: float(row["area_ha"]) for _, row in gdf.iterrows()}

    rows = []
    for cid, d in by_parcel.items():
        total = d["available"] + d["unavailable"] + d["error"]
        pct = round(100.0 * d["available"] / total, 2) if total else None
        mean = sum(d["clouds"])/len(d["clouds"]) if d["clouds"] else None
        rows.append({
            "crop_id": cid,
            "class": class_map.get(cid),
            "class_name": class_name_map.get(cid),
            "area_ha": round(area_map.get(cid, 0.0), 2),
            "months_total": total,
            "months_available": d["available"],
            "months_unavailable": d["unavailable"],
            "months_error": d["error"],
            "pct_available": pct,
            "mean_best_cloud_pct": round(mean, 2) if mean is not None else None,
            "total_candidates_found": d["total_candidates"],
        })
    rows.sort(key=lambda r: (-r["months_available"], -r["area_ha"]))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    logger.info("Parcel CSV guardado en %s (%d filas)", out_path, len(rows))


def print_header(cfg: AppConfig, aoi_gdf: gpd.GeoDataFrame, n_months: int) -> None:
    print()
    print("=" * 72)
    print("  ESTIMATE DATASET MODE (SIN DESCARGA) - PALMA SANTANDER")
    print("=" * 72)
    print(f"  Modo test             : {cfg.test_mode}")
    print(f"  AOIs totales          : {len(aoi_gdf):,}")
    print(f"  Periodo               : {cfg.temporal.start_date} a {cfg.temporal.end_date}")
    print(f"  Meses totales         : {n_months}")
    print(f"  Colección             : {cfg.sentinel.collection}")
    print(f"  Máx. cloud cover      : {cfg.sentinel.max_cloud_cover}%")
    print(f"  Teórico max escenas   : {len(aoi_gdf)*n_months:,}  (AOI × meses)")
    print("=" * 72)
    print()


def estimate_full(cfg_path: str | None = None, assume_yes: bool = False) -> int:
    cfg = load_config(cfg_path)

    aoi_gdf = load_aoi_gdf(cfg.palm.output_aoi_abs)
    aoi_gdf = repair_geometries(aoi_gdf)
    if cfg.test_mode:
        aoi_gdf = subset_for_test_mode(aoi_gdf, test_mode=True, n_parcels=1)
        logger.info("[TEST_MODE] Solo se estima 1 parcela para demostración.")

    months = _parse_start_end(cfg.temporal.start_date, cfg.temporal.end_date)
    print_header(cfg, aoi_gdf, len(months))

    # Confirmación (en producción: 2.434 × 12 = 29k consultas catalog → tardará)
    if not cfg.test_mode and not assume_yes:
        try:
            ans = input(
                f"Estimación sobre {len(aoi_gdf):,} AOIs x {len(months)} meses. "
                "Continuar? [s/N]: "
            ).strip().lower()
        except EOFError:
            ans = ""
        if ans not in {"s", "si", "y", "yes"}:
            logger.info("Cancelado.")
            return 2

    all_records: list[dict] = []
    t0 = time.time()
    parcelas = list(parcel_iterator(cfg, aoi_gdf=aoi_gdf))
    total_parcelas = len(parcelas)
    n_workers = 1 if cfg.test_mode else 8  # test mode: 1 worker, FULL: paralelo x8

    logger.info("Procesando %d parcelas con %d workers (solo Catalog API)...",
                total_parcelas, n_workers)
    try:
        if n_workers == 1:
            # Test mode: 1 a 1, verbose
            for idx, parcel in enumerate(parcelas, start=1):
                crop_id = str(parcel.iloc[0]["crop_id"])
                logger.info("[%d/%d] %s", idx, total_parcelas, crop_id)
                try:
                    all_records.extend(estimate_parcel_months(cfg, parcel))
                except KeyboardInterrupt:
                    logger.warning("Interrupción por teclado. Guardando resultados parciales.")
                    break
                except Exception as e:
                    logger.exception("Parcela %s falló. %s", crop_id, e)
                    continue
        else:
            # Modo FULL: paralelo x8 + barra progreso tqdm
            with ThreadPoolExecutor(max_workers=n_workers, thread_name_prefix="CatalogEst") as ex:
                futures = {
                    ex.submit(estimate_parcel_months, cfg, parcel):
                        str(parcel.iloc[0]["crop_id"])
                    for parcel in parcelas
                }
                with tqdm.tqdm(total=len(futures), desc="Estimate catalog parcels",
                               unit="parcela", ncols=100) as pbar:
                    for fut in as_completed(futures):
                        crop_id = futures[fut]
                        try:
                            result = fut.result()
                            all_records.extend(result)
                        except Exception as e:
                            logger.exception("Parcela %s falló: %s", crop_id, e)
                        pbar.update(1)
    except KeyboardInterrupt:
        logger.warning("Interrupción por teclado. Guardando resultados parciales.")
    t1 = time.time()

    # --- Reportes -------------------------------------------------------
    out_dir = cfg.catalog.save_dir_abs
    out_dir.mkdir(parents=True, exist_ok=True)

    monthly_records_path = out_dir / "estimate_report_monthly.csv"
    save_monthly_csv(all_records, monthly_records_path)

    parcel_report_path = out_dir / "estimate_report_parcels.csv"
    save_parcel_availability(all_records, aoi_gdf, parcel_report_path)

    monthly_summary_rows = summarize_monthly(all_records)
    monthly_summary_csv = out_dir / "estimate_summary_by_month.csv"
    if monthly_summary_rows:
        with open(monthly_summary_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(monthly_summary_rows[0].keys()))
            w.writeheader()
            w.writerows(monthly_summary_rows)

    # --- Summary consola ---------------------------------------------------
    print()
    print("=" * 72)
    print("  RESUMEN POR MES")
    print("=" * 72)
    available_total = 0
    unavailable_total = 0
    error_total = 0
    total_candidates = 0
    for row in monthly_summary_rows:
        print(
            f"  {row['year']:4d}-{row['month']:02d}   "
            f"disponibles: {row['available']:>5}  "
            f"sin datos: {row['unavailable']:>5}  "
            f"errores: {row['error']:>4}  "
            f"mean_cloud={row['mean_best_cloud_pct'] or '-':>5}  "
            f"total_candidates={row['total_candidates_found']:>7}"
        )
        available_total += int(row["available"])
        unavailable_total += int(row["unavailable"])
        error_total += int(row["error"])
        total_candidates += int(row["total_candidates_found"])
    print("-" * 72)
    print(f"  TOTAL disponibles  = {available_total:,}")
    print(f"  TOTAL sin datos= {unavailable_total:,}")
    print(f"  TOTAL errores  = {error_total:,}")
    if total_candidates > 0:
        print(f"  TOTAL candidates (si quieres multi-imagen/mes)= {total_candidates:,}")

    # JSON summary
    summary_json = out_dir / "estimate_summary.json"
    payload = {
        "aoi_count": len(aoi_gdf),
        "months_count": len(months),
        "theoretical_max": len(aoi_gdf) * len(months),
        "start_date": cfg.temporal.start_date,
        "end_date": cfg.temporal.end_date,
        "collection": cfg.sentinel.collection,
        "max_cloud_cover": cfg.sentinel.max_cloud_cover,
        "available_total": available_total,
        "unavailable_total": unavailable_total,
        "error_total": error_total,
        "candidates_total": total_candidates,
        "elapsed_seconds": round(t1 - t0, 1),
        "per_month": monthly_summary_rows,
        "monthly_csv": str(monthly_records_path.name),
        "parcel_csv": str(parcel_report_path.name),
    }
    with open(summary_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Summary JSON: %s", summary_json)
    print(f"\nTiempo estimación: {t1-t0:.1f} s.")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    cfg_arg = next((a for a in args if not a.startswith("-")), None)
    assume_yes = any(a in {"-y", "--yes", "--assume-yes", "--si"} for a in args)
    raise SystemExit(estimate_full(cfg_arg, assume_yes=assume_yes))
