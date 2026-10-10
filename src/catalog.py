"""
catalog.py
==========
Búsqueda de imágenes Sentinel-2 L2A a través de Sentinel Hub Catalog API (STAC).

Endpoint: https://sh.dataspace.copernicus.eu/catalog/v1/search

Soporta:
  - Búsqueda por bbox (WGS84) o geometría GeoJSON
  - Intervalo temporal ISO 8601
  - Filtro por colección (ej: sentinel-2-l2a)
  - Filtro de cobertura nubosa máxima (eo:cloud_cover <= X)
  - Paginación automática siguiendo links.next
  - Guardado opcional de respuestas crudas en data/catalog/
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import requests

from .auth import get_auth
from .config import AppConfig


logger = logging.getLogger(__name__)


CATALOG_URL = "https://sh.dataspace.copernicus.eu/catalog/v1/search"
DEFAULT_TIMEOUT = 60


def _to_iso_utc(value: datetime | str, *, end_of_day: bool = False) -> str:
    """Convierte entrada a string ISO 8601 UTC compatible con STAC.

    Si el input es solo una fecha (YYYY-MM-DD) y end_of_day=False,
    se asume inicio del día 00:00:00Z. Si end_of_day=True, 23:59:59Z.
    """
    if isinstance(value, str):
        s = value.strip()
        # Si ya incluye hora, devolver tal cual (asegurarse Z si es UTC)
        if "T" in s or " " in s:
            if s.endswith("Z"):
                return s
            # si no tiene Z y no tiene offset, asumir UTC
            if not any(tok in s for tok in ("+", "-")):
                # reemplazar espacio por T
                s_norm = s.replace(" ", "T")
                return s_norm + "Z" if not s_norm.endswith("Z") else s_norm
            return s.replace(" ", "T")
        # Caso: YYYY-MM-DD
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            # Caso YYYY-MM-DDTHH:MM:SS sin Z
            return s + "Z" if not s.endswith("Z") else s
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_stac_interval(start: str | datetime, end: str | datetime) -> str:
    """Formato STAC: start/end"""
    return f"{_to_iso_utc(start, end_of_day=False)}/{_to_iso_utc(end, end_of_day=True)}"


def _sanitize_for_filename(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def _maybe_save_response(
    cfg: AppConfig,
    payload: dict,
    response_json: dict,
    page: int,
) -> Optional[Path]:
    if not cfg.catalog.save_responses:
        return None
    out_dir = cfg.catalog.save_dir_abs
    out_dir.mkdir(parents=True, exist_ok=True)
    sig = _sanitize_for_filename(json.dumps(payload, sort_keys=True, default=str))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"search_{sig}_p{page:02d}_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(response_json, f, ensure_ascii=False, indent=2)
    logger.debug("Respuesta de Catalog guardada en %s", out_path)
    return out_path


def _extract_items(response_json: dict) -> list[dict]:
    items = response_json.get("features") or response_json.get("items") or []
    if not isinstance(items, list):
        return []
    return [it for it in items if isinstance(it, dict) and "id" in it]


def _extract_next_link(response_json: dict) -> Optional[str]:
    links = response_json.get("links") or []
    for link in links:
        if link.get("rel") in ("next", "nextPage"):
            href = link.get("href")
            if href:
                return href
    # Algunos endpoints usan context.next
    context = response_json.get("context") or {}
    if isinstance(context, dict):
        nxt = context.get("next")
        if isinstance(nxt, str) and nxt.startswith("http"):
            return nxt
    return None


def _normalize_item(item: dict, collection: str) -> dict:
    """Asegura que el item tenga campos consistentes para el selector."""
    props = item.get("properties") or {}
    # Cobertura nubosa: STAC Sentinel-2 usa "eo:cloud_cover"
    cloud_cover = props.get("eo:cloud_cover")
    if cloud_cover is None:
        cloud_cover = props.get("cloud_cover")
    try:
        cloud_cover = float(cloud_cover) if cloud_cover is not None else 999.0
    except (TypeError, ValueError):
        cloud_cover = 999.0

    geometry = item.get("geometry")
    bbox = item.get("bbox") or []
    if not bbox and geometry is not None:
        # Inferir bbox a partir de geometry
        coords = geometry.get("coordinates") or []
        flat: list[float] = []

        def flatten(c):
            if isinstance(c, (int, float)):
                flat.append(float(c))
            elif isinstance(c, list):
                for e in c:
                    flatten(e)

        flatten(coords)
        if len(flat) >= 4:
            lons = flat[0::2]
            lats = flat[1::2]
            bbox = [min(lons), min(lats), max(lons), max(lats)]

    acquisition_date = props.get("datetime") or props.get("start_datetime") or ""
    # ID Sentinel: productIdentifier si existe, si no item["id"]
    product_id = props.get("s2:product_uri") or props.get("id") or item.get("id")

    return {
        "id": item.get("id"),
        "product_id": product_id,
        "collection": item.get("collection") or collection,
        "type": item.get("type"),
        "geometry": geometry,
        "bbox": list(bbox) if bbox else None,
        "datetime": str(acquisition_date),
        "cloud_cover": cloud_cover,
        "properties": props,
        "assets": item.get("assets") or {},
        "links": item.get("links") or [],
        "stac_version": item.get("stac_version"),
    }


def search_sentinel(
    cfg: AppConfig,
    *,
    bbox: Optional[Iterable[float]] = None,
    geometry: Optional[dict] = None,
    start_date: str | datetime,
    end_date: str | datetime,
    collection: Optional[str] = None,
    max_cloud_cover: Optional[float] = None,
    limit_per_page: Optional[int] = None,
    max_pages: int = 50,
) -> list[dict]:
    """Busca escenas Sentinel-2 vía STAC Catalog.

    Args:
        cfg: Configuración general
        bbox: [minx, miny, maxx, maxy] en WGS84 (EPSG:4326)
        geometry: GeoJSON (Feature o Geometry) en WGS84
        start_date: Fecha inicial (ISO str o datetime)
        end_date: Fecha final
        collection: Por defecto cfg.sentinel.collection
        max_cloud_cover: Por defecto cfg.sentinel.max_cloud_cover
        limit_per_page: Por defecto cfg.catalog.max_results_per_page
        max_pages: Protección contra paginación infinita

    Returns:
        Lista de items normalizados (ver _normalize_item).
    """
    collection = collection or cfg.sentinel.collection
    max_cloud_cover = (
        cfg.sentinel.max_cloud_cover if max_cloud_cover is None else float(max_cloud_cover)
    )
    limit_per_page = (
        cfg.catalog.limit_per_page
        if limit_per_page is None
        else int(limit_per_page)
    )

    if bbox is None and geometry is None:
        raise ValueError("Debes proporcionar `bbox` o `geometry` para la búsqueda.")

    auth = get_auth()
    headers = {
        **auth.get_auth_headers(),
        "Accept": "application/geo+json",
        "Content-Type": "application/json",
    }

    datetime_interval = _build_stac_interval(start_date, end_date)

    # Payload POST de STAC search
    payload: dict[str, Any] = {
        "collections": [collection],
        "datetime": datetime_interval,
        "limit": limit_per_page,
    }
    if bbox is not None:
        bbox_list = list(float(x) for x in bbox)
        if len(bbox_list) != 4:
            raise ValueError(f"bbox debe tener 4 elementos, tiene {len(bbox_list)}")
        payload["bbox"] = bbox_list
    if geometry is not None:
        # Aceptar Feature o Geometry
        if geometry.get("type") == "Feature" and "geometry" in geometry:
            payload["intersects"] = geometry["geometry"]
        else:
            payload["intersects"] = geometry

    # Filtro de cloud_cover (STAC Filter Extension)
    filter_obj = {
        "op": "and",
        "args": [
            {
                "op": "<=",
                "args": [{"property": "eo:cloud_cover"}, max_cloud_cover],
            }
        ],
    }
    payload["filter"] = filter_obj
    payload["filter-lang"] = "cql2-json"

    all_items: list[dict] = []
    page = 0
    next_url: Optional[str] = None

    while True:
        page += 1
        if page > max_pages:
            logger.warning(
                "Se alcanzó el límite de %d páginas; deteniendo paginación.",
                max_pages,
            )
            break

        try:
            if next_url:
                logger.debug("Siguiente página: %s", next_url)
                resp = requests.get(next_url, headers=headers, timeout=DEFAULT_TIMEOUT)
            else:
                logger.info(
                    "[Catalog] Búsqueda: colección=%s, datetime=%s, cloud<=%.1f%%",
                    collection,
                    datetime_interval,
                    max_cloud_cover,
                )
                resp = requests.post(
                    CATALOG_URL, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT
                )
            resp.raise_for_status()
        except requests.HTTPError as e:
            detail = (e.response.text[:800] if e.response is not None else str(e))
            raise RuntimeError(
                f"Error HTTP {getattr(e.response, 'status_code', '?')} en Catalog API: {detail}"
            ) from e
        except requests.RequestException as e:
            raise RuntimeError(f"Error de red en Catalog API: {e}") from e

        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"Respuesta no-JSON de Catalog API: {resp.text[:500]}") from e

        _maybe_save_response(cfg, payload if next_url is None else {"next": next_url}, data, page)

        items = _extract_items(data)
        for raw in items:
            norm = _normalize_item(raw, collection)
            # Filtrado defensivo por cloud_cover por si el filter remoto falla
            if norm["cloud_cover"] <= max_cloud_cover:
                all_items.append(norm)

        logger.info(
            "  Página %d: %d items (acumulados %d, con cloud<=%.1f%%).",
            page,
            len(items),
            len(all_items),
            max_cloud_cover,
        )

        next_url = _extract_next_link(data)
        if not next_url:
            break

    # Ordenar por cloud_cover ascendente (mejores primero)
    all_items.sort(key=lambda it: (it["cloud_cover"], it["datetime"]))
    logger.info(
        "Búsqueda completada: %d escenas disponibles (cloud <= %.1f%%).",
        len(all_items),
        max_cloud_cover,
    )
    return all_items


def summarize_items(items: list[dict]) -> dict:
    """Métricas útiles sobre los resultados."""
    if not items:
        return {"count": 0}
    clouds = [it["cloud_cover"] for it in items]
    dates = sorted(it["datetime"] for it in items if it.get("datetime"))
    return {
        "count": len(items),
        "cloud_min": round(min(clouds), 2),
        "cloud_mean": round(sum(clouds) / len(clouds), 2),
        "cloud_max": round(max(clouds), 2),
        "date_min": dates[0] if dates else None,
        "date_max": dates[-1] if dates else None,
        "unique_ids": sorted({it["id"] for it in items}),
    }
