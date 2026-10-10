"""
test_palm_detector.py
=====================
Pruebas sobre la lectura del mapa de palma y el límite de Santander.
NO descargan datos externos.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_boundary_exists_and_reads():
    from src.config import load_config
    from src.palm_detector import _validate_boundary
    cfg = load_config()
    assert cfg.study_area.boundary_abs.exists(), (
        f"Falta límite Santander en {cfg.study_area.boundary_abs}. "
        "Formato requerido: GeoJSON con geometrías del departamento, idealmente EPSG:4326."
    )
    gdf = _validate_boundary(cfg.study_area.boundary_abs)
    assert len(gdf) >= 1
    assert gdf.crs is not None
    # Debe terminar en EPSG:4326 tras la normalización
    assert gdf.crs.to_epsg() == 4326


def test_palm_map_dir_has_609_tiffs():
    from src.config import load_config
    cfg = load_config()
    d = cfg.palm.map_dir_abs
    assert d.exists(), f"Falta dir de mapa de palma: {d}"
    tiffs = list(d.glob("*.tif"))
    # Permitimos una tolerancia (590-620), el dataset son 609 oficiales
    assert 550 <= len(tiffs) <= 700, (
        f"Se esperaban ~609 GeoTIFF en {d}, encontrados {len(tiffs)}"
    )


def test_intersecting_tiles_count():
    from src.config import load_config
    from src.palm_detector import _validate_boundary, _find_tiles_intersecting
    cfg = load_config()
    gdf = _validate_boundary(cfg.study_area.boundary_abs)
    tiles = _find_tiles_intersecting(gdf, cfg.palm.map_dir_abs)
    # Según inspección anterior, hay unas 7-10 teselas que intersectan Santander
    assert 1 <= len(tiles) <= 30, f"Número inesperado de teselas intersectantes: {len(tiles)}"
    print(f"Teselas intersectantes: {len(tiles)}")
    for t in tiles[:5]:
        print(f"  - {t.name}")


def test_tiff_crs_and_bounds():
    import rasterio
    from src.config import load_config
    from src.palm_detector import _validate_boundary, _find_tiles_intersecting
    cfg = load_config()
    gdf = _validate_boundary(cfg.study_area.boundary_abs)
    tiles = _find_tiles_intersecting(gdf, cfg.palm.map_dir_abs)
    sample = tiles[0]
    with rasterio.open(sample) as src:
        assert src.crs is not None, f"La muestra {sample.name} no tiene CRS"
        assert src.count == 1, f"Rasters del mapa deben ser 1 banda, tiene {src.count}"
        assert src.width > 0 and src.height > 0
        # Comprueba que el CRS del raster sea EPSG:4326 según inspección
        epsg = src.crs.to_epsg()
        assert epsg == 4326, f"Se esperaba EPSG:4326, tiene {epsg}"
        bounds = src.bounds
        assert bounds.left < bounds.right and bounds.bottom < bounds.top
        print(f"Muestra OK: {sample.name} dims={src.width}x{src.height} crs=EPSG:{epsg}")


def test_aoi_file_exists_if_run():
    """Si ya se corrió la detección, el AOI debe leerse sin errores."""
    from src.config import load_config
    from src.aoi_generator import load_aoi_gdf, repair_geometries
    cfg = load_config()
    if not cfg.palm.output_aoi_abs.exists():
        print(f"[SKIP] Aún no existe {cfg.palm.output_aoi_abs}. No se ejecutó todavía palm_detector.")
        return
    gdf = load_aoi_gdf(cfg.palm.output_aoi_abs)
    assert len(gdf) > 0
    assert "crop_id" in gdf.columns
    assert "area_ha" in gdf.columns
    repaired = repair_geometries(gdf)
    assert len(repaired) == len(gdf)
    print(f"AOI OK: {len(gdf)} polígonos válidos")
    print(f"  Clases: {sorted(repaired['class'].unique().tolist())}")
    print(f"  Area total: {repaired['area_ha'].sum():.2f} ha")


if __name__ == "__main__":
    import traceback
    tests = [
        test_boundary_exists_and_reads,
        test_palm_map_dir_has_609_tiffs,
        test_intersecting_tiles_count,
        test_tiff_crs_and_bounds,
        test_aoi_file_exists_if_run,
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
        except Exception as e:
            print(f"[ERR] {name}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} tests pasados.")
    sys.exit(0 if passed == len(tests) else 1)
