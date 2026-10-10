"""
image_selector.py
=================
Dado un AOI y un rango temporal, selecciona la MEJOR imagen Sentinel-2 L2A
de cada mes (menor cobertura nubosa).

IMPORTANTE:
  - Si un mes no tiene imagen válida -> status = "unavailable"
  - NO se inventa ninguna imagen
  - NO se duplica automáticamente otro mes
  - Se guarda un archivo de decisiones para reproducibilidad
"""
from __future__ import annotations

import json
import logging
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import AppConfig
from .aoi_generator import get_bbox_wgs84, get_geometry_as_geojson
from .catalog import search_sentinel, summarize_items


logger = logging.getLogger(__name__)


@dataclass
class MonthlySelection:
    crop_id: str
    year: int
    month: int  # 1-12
    status: str  # "available" | "unavailable"
    selected_item: Optional[dict] = None
    cloud_cover: Optional[float] = None
    acquisition_date: Optional[str] = None
    product_id: Optional[str] = None
    candidates_count: int = 0
    candidates_summary: Optional[dict] = None


def _month_interval(year: int, month: int) -> tuple[str, str]:
    last_day = monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{last_day:02d}"
    return start, end


def _parse_start_end(start_date: str, end_date: str) -> list[tuple[int, int]]:
    s = datetime.strptime(start_date[:10], "%Y-%m-%d")
    e = datetime.strptime(end_date[:10], "%Y-%m-%d")
    months: list[tuple[int, int]] = []
    y, m = s.year, s.month
    while (y, m) <= (e.year, e.month):
        months.append((y, m))
        m += 1
        if m > 12:
            y += 1
            m = 1
    return months


def _pick_best(items: list[dict]) -> Optional[dict]:
    """Estrategia: menor cloud_cover; desempate por fecha más cercana al centro del mes."""
    if not items:
        return None
    return sorted(items, key=lambda it: (it["cloud_cover"], it["datetime"]))[0]


def select_monthly_for_parcel(
    cfg: AppConfig,
    *,
    parcel_row: Any,
) -> list[MonthlySelection]:
    """Para una única parcela, realiza una búsqueda Catalog por cada mes y
    devuelve la lista de selecciones mensuales.
    """
    crop_id = parcel_row["crop_id"]
    geometry = parcel_row.geometry
    bbox = get_bbox_wgs84(geometry)
    geom_geojson = get_geometry_as_geojson(geometry)

    months = _parse_start_end(cfg.temporal.start_date, cfg.temporal.end_date)
    if not months:
        raise ValueError(
            f"Rango temporal vacío: {cfg.temporal.start_date} a {cfg.temporal.end_date}"
        )

    logger.info(
        "[Parcel %s] Selección mensual: %d meses (%s a %s), cloud<=%.1f%%",
        crop_id,
        len(months),
        cfg.temporal.start_date,
        cfg.temporal.end_date,
        cfg.sentinel.max_cloud_cover,
    )

    selections: list[MonthlySelection] = []
    for year, month in months:
        start, end = _month_interval(year, month)
        logger.info("  Buscando %04d-%02d (%s -> %s)...", year, month, start, end)

        try:
            items = search_sentinel(
                cfg,
                bbox=bbox,
                geometry=geom_geojson,
                start_date=start,
                end_date=end,
            )
        except Exception as e:
            logger.warning(
                "    Falla en búsqueda %04d-%02d: %s. Marcando unavailable.",
                year,
                month,
                e,
            )
            items = []

        summary = summarize_items(items)
        best = _pick_best(items)

        if best is None:
            sel = MonthlySelection(
                crop_id=crop_id,
                year=year,
                month=month,
                status="unavailable",
                selected_item=None,
                cloud_cover=None,
                acquisition_date=None,
                product_id=None,
                candidates_count=len(items),
                candidates_summary=summary,
            )
            logger.info("    -> No hay imágenes válidas -> UNAVAILABLE")
        else:
            sel = MonthlySelection(
                crop_id=crop_id,
                year=year,
                month=month,
                status="available",
                selected_item=best,
                cloud_cover=float(best["cloud_cover"]),
                acquisition_date=str(best["datetime"]),
                product_id=best["product_id"] or best["id"],
                candidates_count=len(items),
                candidates_summary=summary,
            )
            logger.info(
                "    -> Seleccionada: %s (cloud=%.2f%% @ %s) entre %d candidatas",
                best["id"],
                sel.cloud_cover,
                sel.acquisition_date,
                sel.candidates_count,
            )

        selections.append(sel)

    available = sum(1 for s in selections if s.status == "available")
    logger.info(
        "[Parcel %s] Selección completada: %d/%d meses disponibles",
        crop_id,
        available,
        len(selections),
    )
    return selections


def selections_to_dict(selections: list[MonthlySelection]) -> list[dict]:
    out = []
    for s in selections:
        d = asdict(s)
        # selected_item ya es un dict grande; lo mantenemos completo
        out.append(d)
    return out


def save_selections_report(
    selections: list[MonthlySelection], out_path: str | Path
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = selections_to_dict(selections)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Reporte de selecciones guardado en %s", out_path)
    return out_path
