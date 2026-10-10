from pathlib import Path
import rasterio
import numpy as np


PALM_MAP_DIR = Path("data/palm_map/GlobalOilPalm_OP-extent")

SANTANDER_MIN_LON = -74.5
SANTANDER_MAX_LON = -72.5
SANTANDER_MIN_LAT = 5.5
SANTANDER_MAX_LAT = 8.5


tif_files = list(PALM_MAP_DIR.glob("*.tif"))

print(f"GeoTIFF encontrados: {len(tif_files)}")

print("\nAnalizando valores de las teselas de Santander...\n")


for tif in tif_files:

    with rasterio.open(tif) as src:

        bounds = src.bounds

        intersects = not (
            bounds.right < SANTANDER_MIN_LON
            or bounds.left > SANTANDER_MAX_LON
            or bounds.top < SANTANDER_MIN_LAT
            or bounds.bottom > SANTANDER_MAX_LAT
        )

        if not intersects:
            continue

        print("=" * 60)
        print(f"Archivo: {tif.name}")
        print(f"Bounds: {bounds}")
        print(f"CRS: {src.crs}")

        data = src.read(1)

        values, counts = np.unique(data, return_counts=True)

        print("\nValores encontrados:")

        for value, count in zip(values, counts):

            print(f"  Valor {value}: {count:,} píxeles")

        print()