"""
test_catalog.py
===============
Pruebas del módulo Catalog.

- NO ejecuta búsquedas reales para evitar consumo de cuota.
- Verifica construcción correcta de intervalos STAC, normalización de items,
  validación de bbox, manejo de unavailable.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_stac_interval_iso():
    from src.catalog import _build_stac_interval
    s, e = "2025-01-01", "2025-01-31"
    interval = _build_stac_interval(s, e)
    print(f"Interval: {interval}")
    assert interval.startswith("2025-01-01T00:00:00Z/")
    assert interval.endswith("T23:59:59Z")
    assert "/2025-01-31" in interval


def test_month_interval():
    from src.image_selector import _month_interval
    start, end = _month_interval(2025, 2)
    assert start == "2025-02-01"
    assert end == "2025-02-28"  # 2025 no es bisiesto
    start, end = _month_interval(2024, 2)
    assert end == "2024-02-29"  # 2024 bisiesto


def test_parse_start_end_month_list():
    from src.image_selector import _parse_start_end
    months = _parse_start_end("2025-01-01", "2025-12-31")
    assert len(months) == 12
    assert months[0] == (2025, 1)
    assert months[-1] == (2025, 12)


def test_normalize_item_fills_defaults():
    from src.catalog import _normalize_item
    raw = {
        "id": "S2A_MSIL2A_20250105T152631_N0510_R025_T18NXL_20250105T190100",
        "geometry": {"type": "Polygon", "coordinates": [[[-74,5],[-73,5],[-73,6],[-74,6],[-74,5]]]},
        "properties": {
            "datetime": "2025-01-05T15:31:23Z",
            "eo:cloud_cover": "12.3",
            "s2:product_uri": "S2A_MSIL2A_20250105T152631_N0510_R025_T18NXL_20250105T190100.SAFE",
        },
    }
    norm = _normalize_item(raw, "sentinel-2-l2a")
    assert norm["id"] == raw["id"]
    assert norm["cloud_cover"] == 12.3
    assert norm["collection"] == "sentinel-2-l2a"
    assert norm["datetime"].startswith("2025-01-05T15:31:23")
    assert norm["bbox"] is not None and len(norm["bbox"]) == 4


def test_pick_best_prefers_lower_cloud():
    from src.image_selector import _pick_best
    items = [
        {"id": "a", "cloud_cover": 20.0, "datetime": "2025-01-05"},
        {"id": "b", "cloud_cover": 5.0,  "datetime": "2025-01-10"},
        {"id": "c", "cloud_cover": 10.0, "datetime": "2025-01-15"},
    ]
    best = _pick_best(items)
    assert best["id"] == "b"
    assert _pick_best([]) is None


def test_summary_items():
    from src.catalog import summarize_items
    items = [
        {"id": "a", "cloud_cover": 10.0, "datetime": "2025-01-05"},
        {"id": "b", "cloud_cover": 5.0, "datetime": "2025-01-10"},
    ]
    s = summarize_items(items)
    assert s["count"] == 2
    assert s["cloud_min"] == 5.0
    assert s["cloud_max"] == 10.0


def test_aoi_subset_test_mode():
    import geopandas as gpd
    from shapely.geometry import box
    from src.aoi_generator import subset_for_test_mode
    gdf = gpd.GeoDataFrame(
        {
            "crop_id": [f"PALMA_{i:04d}" for i in range(1, 6)],
            "area_ha": [100.0, 200.0, 50.0, 300.0, 80.0],
            "class": [1, 2, 1, 1, 2],
        },
        geometry=[box(0, 0, 1, 1)] * 5,
        crs="EPSG:4326",
    )
    subset = subset_for_test_mode(gdf, test_mode=True, n_parcels=2)
    # PALMA_0004 = 300 ha mayor, PALMA_0002 = 200 ha segundo mayor
    assert list(subset["crop_id"]) == ["PALMA_0004", "PALMA_0002"]
    no_subset = subset_for_test_mode(gdf, test_mode=False)
    assert len(no_subset) == 5


def test_cloud_mask_from_scl_known_classes():
    import numpy as np
    from src.cloud_mask import (
        build_cloud_mask_from_scl,
        CLOUD_MASK_VALID,
        CLOUD_MASK_INVALID,
        CLOUD_MASK_NODATA,
        SCL_CLOUD_HIGH,
        SCL_CIRRUS,
        SCL_VEGETATION,
        SCL_NO_DATA,
    )
    scl = np.array([
        [SCL_NO_DATA, SCL_VEGETATION, SCL_CLOUD_HIGH],
        [SCL_VEGETATION, SCL_CIRRUS, SCL_VEGETATION],
    ], dtype=np.uint8)
    mask = build_cloud_mask_from_scl(scl)
    assert mask.shape == scl.shape
    assert mask[0, 0] == CLOUD_MASK_NODATA
    assert mask[0, 1] == CLOUD_MASK_VALID
    assert mask[0, 2] == CLOUD_MASK_INVALID
    assert mask[1, 1] == CLOUD_MASK_INVALID
    assert mask[1, 0] == CLOUD_MASK_VALID


def test_preprocessing_validate_report():
    """Sin descargar, solo construye un pequeño raster falso y valida."""
    import tempfile
    import numpy as np
    import rasterio
    from rasterio.crs import CRS as RioCRS
    from src.preprocessing import validate_target_image
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "small.tif"
        H, W = 32, 32
        bands = ["B02", "B03", "B04"]
        arr = np.random.rand(3, H, W).astype("float32")
        profile = {
            "driver": "GTiff",
            "height": H, "width": W, "count": 3,
            "dtype": "float32",
            "crs": RioCRS.from_epsg(4326),
            "transform": rasterio.transform.from_bounds(-74.0, 7.0, -73.99, 7.01, W, H),
        }
        with rasterio.open(path, "w", **profile) as dst:
            for i, b in enumerate(bands, start=1):
                dst.write(arr[i-1], i)
                dst.set_band_description(i, b)
        info = validate_target_image(path, bands)
        assert info["exists"] is True
        assert info["width"] == W and info["height"] == H
        assert info["crs_ok"] is True


if __name__ == "__main__":
    import traceback
    tests = [
        test_stac_interval_iso,
        test_month_interval,
        test_parse_start_end_month_list,
        test_normalize_item_fills_defaults,
        test_pick_best_prefers_lower_cloud,
        test_summary_items,
        test_aoi_subset_test_mode,
        test_cloud_mask_from_scl_known_classes,
        test_preprocessing_validate_report,
    ]
    passed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            print(f"[OK]  {name}")
            passed += 1
        except AssertionError as e:
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()
        except Exception as e:
            print(f"[ERR] {name}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} tests pasados.")
    sys.exit(0 if passed == len(tests) else 1)
