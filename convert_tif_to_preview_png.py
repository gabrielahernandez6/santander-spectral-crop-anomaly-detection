"""Convierte el GeoTIFF multibanda del proyecto (12 bandas L2A) en 4 PNG de
previsualización que se pueden abrir CUALQUIER visor de imágenes de Windows.

Salidas generadas:
    data/processed/palma/PALMA_XXXX/YYYY-MM_preview_TRUE_COLOR.png  (RGB=B04/B03/B02)
    data/processed/palma/PALMA_XXXX/YYYY-MM_preview_FALSE_COLOR.png (RGB=B08/B04/B03)
    data/processed/palma/PALMA_XXXX/YYYY-MM_preview_NDVI.png        (colormap viridis, NDVI=(B08-B04)/(B08+B04))
    data/processed/palma/PALMA_XXXX/YYYY-MM_preview_CLOUD_MASK.png  (blanco=válido, rojo=nube, negro=nodata)

Uso:
    python convert_tif_to_preview_png.py [data/processed/palma/PALMA_0001/2025-01.tif]

Si no pasas argumento, usa automáticamente el TIFF más reciente de
data/processed/palma/PALMA_0001/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import rasterio
from matplotlib import cm
from matplotlib.colors import Normalize
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent
PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed" / "palma"


def _linear_pct_stretch(arr: np.ndarray, pmin: float = 2.0, pmax: float = 98.0) -> np.ndarray:
    """Estira histograma (recorte percentil) para visualización humana.
    Elimina outliers de brillo/oscuridad y coloca valores a rango [0,255] uint8.
    """
    valid = arr[~np.isnan(arr)]
    if valid.size == 0:
        return np.zeros_like(arr, dtype=np.uint8)
    lo, hi = np.percentile(valid, [pmin, pmax])
    if hi - lo <= 1e-8:
        return np.zeros_like(arr, dtype=np.uint8)
    stretched = np.clip((arr.astype(np.float32) - lo) / (hi - lo), 0.0, 1.0)
    stretched = np.nan_to_num(stretched, nan=0.0)
    return (stretched * 255.0).astype(np.uint8)


def _stack_rgb(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    r8 = _linear_pct_stretch(r)
    g8 = _linear_pct_stretch(g)
    b8 = _linear_pct_stretch(b)
    return np.stack([r8, g8, b8], axis=-1)  # (H, W, 3)


def _save_png(arr_hwc: np.ndarray, out_path: Path) -> None:
    Image.fromarray(arr_hwc).save(out_path, format="PNG", optimize=True)


def process_tif(tif_path: Path) -> dict[str, Path]:
    if not tif_path.exists():
        raise FileNotFoundError(tif_path)

    with rasterio.open(tif_path) as src:
        band_names = list(src.descriptions) or [f"B{i+1:02d}" for i in range(src.count)]
        bands_idx = {name: i + 1 for i, name in enumerate(band_names)}
        b02 = src.read(bands_idx["B02"]).astype(np.float32)
        b03 = src.read(bands_idx["B03"]).astype(np.float32)
        b04 = src.read(bands_idx["B04"]).astype(np.float32)
        b08 = src.read(bands_idx["B08"]).astype(np.float32)
        b11 = src.read(bands_idx["B11"]).astype(np.float32)

    out_dir = tif_path.parent
    stem = tif_path.stem  # "2025-01"

    # 1) TRUE COLOR (RGB: B04 Rojo, B03 Verde, B02 Azul)
    rgb_true = _stack_rgb(b04, b03, b02)
    out_true = out_dir / f"{stem}_preview_TRUE_COLOR.png"
    _save_png(rgb_true, out_true)

    # 2) FALSE COLOR (B08 NIR=Rojo, B04=Verde, B03=Azul)  vegetacion R intensa
    rgb_false = _stack_rgb(b08, b04, b03)
    out_false = out_dir / f"{stem}_preview_FALSE_COLOR.png"
    _save_png(rgb_false, out_false)

    # 3) NDVI color map
    ndvi_num = b08 - b04
    ndvi_den = b08 + b04
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(ndvi_den > 1e-6, ndvi_num / ndvi_den, np.nan)
    ndvi_valid = ndvi[~np.isnan(ndvi)]
    vmin = np.percentile(ndvi_valid, 2) if ndvi_valid.size else 0.0
    vmax = np.percentile(ndvi_valid, 98) if ndvi_valid.size else 1.0
    norm = Normalize(vmin=max(vmin, -1.0), vmax=min(vmax, 1.0), clip=True)
    ndvi_clean = np.nan_to_num(ndvi, nan=vmin - 1e-6)
    rgba = cm.viridis(norm(ndvi_clean))  # (H, W, 4) float 0..1
    rgba8 = (np.clip(rgba, 0, 1) * 255).astype(np.uint8)
    out_ndvi = out_dir / f"{stem}_preview_NDVI.png"
    _save_png(rgba8, out_ndvi)

    # 4) CLOUD MASK (si la existe)
    mask_path = out_dir / f"{stem}_cloud_mask.tif"
    out_mask = None
    if mask_path.exists():
        with rasterio.open(mask_path) as src:
            m = src.read(1)
        # Blanco=válido (1), Rojo=nube (0), Negro=nodata (255 or else)
        rgb_mask = np.zeros((m.shape[0], m.shape[1], 3), dtype=np.uint8)
        rgb_mask[m == 1] = [255, 255, 255]
        rgb_mask[m == 0] = [255, 0, 0]
        nodata = m == 255
        rgb_mask[nodata] = [0, 0, 0]
        out_mask = out_dir / f"{stem}_preview_CLOUD_MASK.png"
        _save_png(rgb_mask, out_mask)

    out_paths = {
        "TRUE_COLOR": out_true,
        "FALSE_COLOR": out_false,
        "NDVI": out_ndvi,
    }
    if out_mask:
        out_paths["CLOUD_MASK"] = out_mask
    return out_paths


def main() -> int:
    if len(sys.argv) > 1:
        tif_path = Path(sys.argv[1]).resolve()
    else:
        # Auto: primer TIF de PALMA_0001 con patrón exacto YYYY-MM.tif (NO *_cloud_mask.tif)
        import re
        default = PROCESSED_ROOT / "PALMA_0001"
        yyyy_mm = re.compile(r"^\d{4}-\d{2}\.tif$")
        tifs = sorted(p for p in default.glob("*.tif") if yyyy_mm.match(p.name)) if default.exists() else []
        if not tifs:
            print(f"[ERR] No pasaste ruta .tif y no se encontró ninguno en {default} con patrón YYYY-MM.tif")
            print("  Uso: python convert_tif_to_preview_png.py  data/processed/palma/PALMA_XXXX/2025-01.tif")
            return 2
        tif_path = tifs[-1]

    print(f"[INFO] Convirtiendo: {tif_path}")
    result = process_tif(tif_path)
    print(f"[OK  ] Imágenes preview PNG generadas:")
    for name, path in result.items():
        size_kb = round(path.stat().st_size / 1024, 1)
        print(f"    {name:14s} -> {path}  ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
