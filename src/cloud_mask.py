"""
cloud_mask.py
=============
Máscara de nubes usando SCL (Scene Classification Layer) de Sentinel-2 L2A.

Clases SCL (ESA):
  0  No data / missing
  1  Saturated / defective
  2  Dark area pixels
  3  Cloud shadows
  4  Vegetation
  5  Bare soils
  6  Water
  7  Clouds low probability / unclassified
  8  Clouds medium probability
  9  Clouds high probability
  10 Cirrus
  11 Snow / ice

El algoritmo marca como inválidos (cloud mask = 0) píxeles:
  - No data / defectuosos
  - Sombras de nube (cloud shadows)
  - Nubes (baja/media/alta probabilidad)
  - Cirrus

Píxeles válidos (cloud mask = 1): vegetación, suelo, agua, nieve (por defecto).

No borramos la imagen si algunos píxeles están nublados: la máscara se guarda por separado.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio

logger = logging.getLogger(__name__)


# Sentinel-2 L2A SCL classes (ESA)
SCL_NO_DATA = 0
SCL_SATURATED_DEFECTIVE = 1
SCL_DARK_AREA = 2
SCL_CLOUD_SHADOW = 3
SCL_VEGETATION = 4
SCL_BARE_SOIL = 5
SCL_WATER = 6
SCL_CLOUD_LOW = 7
SCL_CLOUD_MED = 8
SCL_CLOUD_HIGH = 9
SCL_CIRRUS = 10
SCL_SNOW = 11

# Mask values
CLOUD_MASK_VALID = 1
CLOUD_MASK_INVALID = 0
CLOUD_MASK_NODATA = 255


def build_cloud_mask_from_scl(scl: np.ndarray) -> np.ndarray:
    """Convierte SCL (uint8, HxW) a una máscara uint8 (HxW) con:
    1 = píxel válido, 0 = inválido (nubes/cirrus/sombras/nodata/saturado).
    """
    if scl.ndim == 3 and scl.shape[0] == 1:
        scl = scl[0]
    if scl.ndim != 2:
        raise ValueError(f"SCL debe ser HxW, tiene shape {scl.shape}")

    invalid_classes = {
        SCL_NO_DATA,
        SCL_SATURATED_DEFECTIVE,
        SCL_CLOUD_SHADOW,
        SCL_CLOUD_LOW,
        SCL_CLOUD_MED,
        SCL_CLOUD_HIGH,
        SCL_CIRRUS,
    }

    valid_mask = ~np.isin(scl, list(invalid_classes))
    mask = np.where(valid_mask, CLOUD_MASK_VALID, CLOUD_MASK_INVALID).astype(np.uint8)

    # Marcar NoData explícitamente como 255 (para distinguir de nubes)
    nodata = scl == SCL_NO_DATA
    mask = np.where(nodata, CLOUD_MASK_NODATA, mask)

    stats = {
        "total": int(mask.size),
        "valid_pct": round(100 * float((mask == CLOUD_MASK_VALID).sum()) / max(1, mask.size), 2),
        "cloud_pct": round(100 * float((mask == CLOUD_MASK_INVALID).sum()) / max(1, mask.size), 2),
        "nodata_pct": round(100 * float((mask == CLOUD_MASK_NODATA).sum()) / max(1, mask.size), 2),
    }
    logger.debug("Cloud mask SCL stats: %s", stats)
    return mask


def compute_pixel_cloud_cover_from_mask(cloud_mask: np.ndarray) -> float:
    """Cobertura nubosa del AOI (0-100%) usando la máscara local."""
    if cloud_mask.size == 0:
        return 100.0
    total_valid_mask = cloud_mask != CLOUD_MASK_NODATA
    denom = int(total_valid_mask.sum())
    if denom == 0:
        return 100.0
    cloud_pixels = int((cloud_mask[total_valid_mask] == CLOUD_MASK_INVALID).sum())
    return round(100.0 * cloud_pixels / denom, 2)


def read_cloud_mask(mask_path: str | Path) -> np.ndarray:
    mask_path = Path(mask_path)
    if not mask_path.exists():
        raise FileNotFoundError(f"No se encontró cloud mask: {mask_path}")
    with rasterio.open(mask_path) as src:
        return src.read(1)


def scl_statistics(scl: np.ndarray) -> dict:
    """Cuenta cuántos píxeles caen en cada clase SCL."""
    counts = {c: 0 for c in range(12)}
    values, cnts = np.unique(scl, return_counts=True)
    for v, c in zip(values, cnts):
        try:
            counts[int(v)] = int(c)
        except (ValueError, KeyError):
            pass
    pct = {k: round(100 * v / max(1, scl.size), 3) for k, v in counts.items()}
    return {"counts": counts, "pct": pct}
