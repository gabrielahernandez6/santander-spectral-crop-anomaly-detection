"""
download_test.py
================
FUERZA una descarga directa SIN pasar por todo el pipeline.
Usa: PALMA_0001 (la más grande) y el PRIMER MES disponible (en tu estimación fue
2025-01 con 3 candidatos y mejor cloud cover 1.46%).

Podemos elegir mes manualmente abajo si quieres otro.

Resultado final en:
  data/processed/palma/PALMA_0001/
     ├── 2025-01.tif           (12 bandas L2A, 10 m)
     ├── 2025-01_cloud_mask.tif
     └── 2025-01_metadata.json
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import rasterio

# logging simple (antes de importar cfg que también configure logging)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("DLTEST")

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_config
from src.aoi_generator import load_aoi_gdf, repair_geometries, get_bbox_wgs84
from src.catalog import search_sentinel
from src.image_selector import _pick_best, _month_interval
from src.downloader import download_monthly_image
from src.image_selector import MonthlySelection  # noqa: E402  (después sys.path)


def inspect_output(path: Path) -> None:
    print()
    print("=" * 72)
    print("  VALIDACIÓN: GeoTIFF descargado:  ", path.name)
    print("=" * 72)
    with rasterio.open(path) as ds:
        print(f"  path              : {path}")
        print(f"  driver            : {ds.driver}")
        print(f"  width             : {ds.width} px")
        print(f"  height            : {ds.height} px")
        print(f"  bandas (count)    : {ds.count}")
        print(f"  dtype (1ª banda)  : {ds.dtypes[0]}")
        print(f"  crs               : {ds.crs}")
        print(f"  nodata            : {ds.nodata}")
        res_x, res_y = ds.res
        print(f"  resolución x      : {res_x:.8f}  (~{res_x*111319.5:.2f} m en lat aprox)")
        print(f"  resolución y      : {abs(res_y):.8f}  (~{abs(res_y)*111319.5:.2f} m en lat aprox)")
        print(f"  bounds (WGS84?)   : {ds.bounds}")
        print(f"  transform         : {ds.transform}")
        print(f"  band descriptions : {ds.descriptions}")

        # Estadísticos básicos por banda
        print()
        print("  Estadísticos por banda (min / mean / max / std):")
        data = ds.read()
        for i in range(ds.count):
            b = data[i].ravel()
            valid = b[~np.isnan(b)] if np.issubdtype(b.dtype, np.floating) else b[b != ds.nodata] if ds.nodata is not None else b
            if valid.size == 0:
                print(f"    B{i+1:>2} ({ds.descriptions[i] or ''}): SIN DATOS VÁLIDOS")
                continue
            print(
                f"    B{i+1:>2} ({ds.descriptions[i] or '':>3}): "
                f"min={np.min(valid):.4f}  mean={np.mean(valid):.4f}  "
                f"max={np.max(valid):.4f}  std={np.std(valid):.4f}"
            )


def main() -> int:
    cfg = load_config()

    # ----------- 1) Cargamos AOI y tomamos PALMA_0001 -----------------------
    gdf_raw = load_aoi_gdf(cfg.palm.output_aoi_abs)
    gdf = repair_geometries(gdf_raw)
    gdf = gdf.sort_values("area_ha", ascending=False).reset_index(drop=True)
    palma_row = gdf.iloc[0]
    crop_id = str(palma_row["crop_id"])
    logger.info("Parcela elegida: %s (%.2f ha, %s)",
                crop_id, float(palma_row["area_ha"]), str(palma_row["class_name"]))
    logger.info("bbox WGS84: %s", list(get_bbox_wgs84(palma_row.geometry)))

    # ----------- 2) ELEGIR MES ------------------------------------------------
    # Puedes cambiar manualmente año y mes aquí si quieres otro:
    YEAR = 2025
    MONTH = 1  # Enero (mejor cloud cover = 1.46%, 3 candidatas disponibles)
    start, end = _month_interval(YEAR, MONTH)
    logger.info("Consultando Catalog para %04d-%02d (%s -> %s)...",
                YEAR, MONTH, start, end)

    # ----------- 3) Catalog API ---------------------------------------------
    bbox = list(get_bbox_wgs84(palma_row.geometry))
    items = search_sentinel(
        cfg,
        bbox=bbox,
        start_date=start,
        end_date=end,
    )
    logger.info("Catalog devolvió %d escenas con cloud<=%s%%.",
                len(items), cfg.sentinel.max_cloud_cover)
    if not items:
        logger.error("NINGUNA escena. Cambia mes/ año o sube max_cloud_cover.")
        return 3

    # Top-5 por menor cloud cover
    items_sorted = sorted(items, key=lambda i: i.get("cloud_cover") or 9999)
    print()
    print("Top escenas:")
    for i, it in enumerate(items_sorted[:5], start=1):
        print(f"  #{i}  cloud={it.get('cloud_cover'):>5.1f}%   "
              f"date={str(it.get('datetime'))[:10]}   "
              f"product_id={str(it.get('product_id'))[:70]}")

    best = _pick_best(items)
    assert best is not None
    sel = MonthlySelection(
        crop_id=crop_id,
        year=YEAR,
        month=MONTH,
        status="available",
        selected_item=best,
        cloud_cover=best.get("cloud_cover"),
        acquisition_date=str(best.get("datetime"))[:10],
        product_id=str(best.get("product_id")),
        candidates_count=len(items),
        candidates_summary=[
            {"date": str(x.get("datetime"))[:10],
             "cloud_cover": x.get("cloud_cover"),
             "product_id": str(x.get("product_id"))}
            for x in items_sorted[:10]
        ],
    )
    print()
    logger.info("Seleccionada: %s  cloud=%.2f%%  product=%s",
                sel.acquisition_date,
                float(sel.cloud_cover or 0),
                str(sel.product_id)[:70])

    # ----------- 4) DESCARGAR via Process API -------------------------------
    logger.info("Iniciando descarga Sentinel Hub Process API...")
    parcel_df = gdf.iloc[[0]]
    out_tif, out_mask = download_monthly_image(
        cfg, parcel_row=palma_row, selection=sel,
    )
    if out_tif is None:
        logger.error("download_monthly_image devolvió None. Revisa logs arriba.")
        return 4
    logger.info("Descarga OK.")
    logger.info("  Imagen     : %s", out_tif)
    logger.info("  Cloud mask : %s", out_mask)

    # ----------- 5) Validación del GeoTIFF resultante -----------------------
    inspect_output(out_tif)

    # ----------- 6) Guardamos un pequeño reporte de la descarga -------------
    report_dir = out_tif.parent
    summary = {
        "crop_id": crop_id,
        "class": int(palma_row["class"]),
        "class_name": str(palma_row["class_name"]),
        "area_ha": float(palma_row["area_ha"]),
        "selection_month": f"{YEAR:04d}-{MONTH:02d}",
        "acquisition_date": sel.acquisition_date,
        "product_id": sel.product_id,
        "cloud_cover_scene_pct": sel.cloud_cover,
        "output_image": str(out_tif),
        "output_cloud_mask": str(out_mask),
    }
    with open(report_dir / "download_test_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Reporte: %s", report_dir / "download_test_summary.json")

    print()
    logger.info("LISTO 🎉. Descarga y validación completadas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
