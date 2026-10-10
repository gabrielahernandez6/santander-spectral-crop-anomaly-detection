"""SOLO LECTURA - Inspecciona TODOS los archivos vectoriales del proyecto para TFG.
   Imprime: nombre de archivo, ruta, columnas, CRS, num filas, primera fila,
   y las columnas típicas de fuente cartográfica colombiana.
"""
import sys, json
from pathlib import Path
import geopandas as gpd

ROOT = Path(__file__).resolve().parent / "data"
# Búsqueda vectorial EXCLUYENDO .venv
files = [
    p for p in list(ROOT.rglob("*.shp")) + list(ROOT.rglob("*.geojson")) + list(ROOT.rglob("*.gpkg")) + list(ROOT.rglob("*.kml")) + list(ROOT.rglob("*.kmz"))
    if ".venv" not in str(p)
]
files += [p for p in (ROOT.rglob("*.zip")) if ".venv" not in str(p) and (p.name.startswith("MGN") or "MGN" in p.name or "dane" in p.name.lower() or "igac" in p.name.lower())]

# Si existe MGN zip: reportar su nombre/tamaño sin descomprimir
import zipfile

print("=" * 110)
print("   REPORTE FUENTES CARTOGRÁFICAS / ARCHIVOS VECTORIALES EN data/")
print("=" * 110)

# Primero los zips MGn etc
zips = sorted([p for p in ROOT.rglob("*.zip") if ".venv" not in str(p)])
if zips:
    print()
    print("🔍 Zips encontrados en data/ :")
    for z in zips:
        mb = z.stat().st_size / 1024 / 1024
        print(f"  · {z.name:<55s}  {mb:>8.2f} MB   ->  {z.parent}")

print()
print(f"📦 Archivos vectoriales: {len(files)}")
print()
for idx, p in enumerate(files, 1):
    print("─" * 110)
    print(f"#{idx:02d} · {p.name}")
    print(f"      ruta : {p}")
    try:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                shp_files = [n for n in names if n.lower().endswith(".shp")]
                print(f"      tipo : ZIP ({len(names)} archivos internos · {len(shp_files)} .shp)")
                if shp_files:
                    print(f"      SHP interno (primer match) -> {shp_files[0]}")
                    gdf = gpd.read_file(f"zip://{p}!/{shp_files[0]}")
                else:
                    print("      ❌ No hay .shp dentro del zip (revísalo manualmente).")
                    continue
        else:
            gdf = gpd.read_file(p)
            print(f"      tipo : {p.suffix.upper().lstrip('.')}")
    except Exception as e:
        print(f"      ❌ No se pudo leer: {type(e).__name__}: {e}")
        continue

    print(f"      CRS  : {gdf.crs}")
    print(f"      filas: {len(gdf):,}  columnas: {len(gdf.columns)}")
    print(f"      cols : {list(gdf.columns)}")
    # Columnas clave para identificar fuente
    CLUES = [c for c in gdf.columns if any(
        x in c.lower()
        for x in ("dane","igac","mgn","depto","dep","departamento","cod_dep","dp","dpnm","version","anio","año","year","cnt","shape","nombre","coddpt","dpt","nom_dpt")
    )]
    if CLUES:
        print(f"      🔎 COLS CLAVE: {CLUES}")
        try:
            row0 = gdf.iloc[0]
            vals = {c: (row0[c] if not isinstance(row0[c], (dict,)) else str(row0[c])[:60]) for c in CLUES if c in gdf.columns}
            print(f"      [fila 0]: {vals}")
        except Exception as e2:
            print(f"      (no pude imprimir fila 0: {e2})")

    # Si es Santander boundary, imprime atributos departamento
    if p.name.lower() in ("santander.geojson","departamento.geojson","limite_santander.geojson") or ("santander" in p.name.lower() and p.suffix.lower() in (".geojson",".shp",".gpkg")):
        print("      🏁  Detectado AOI SANTANDER — primera fila completa:")
        try:
            r0 = gdf.iloc[0]
            for c in gdf.columns:
                if c == "geometry": continue
                v = r0[c]
                if isinstance(v, (dict, list)): v = json.dumps(v, ensure_ascii=False)[:80]
                print(f"         · {c:<30s} = {v}")
        except Exception: pass

print()
print("=" * 110)
sys.exit(0)
