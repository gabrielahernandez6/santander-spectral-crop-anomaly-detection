"""Imágenes PNG de cada capa, listas para superponer en el mapa (RGBA, transparente donde no aplica)."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

# Paradas de las paletas de matplotlib (muestreadas a intervalos iguales).
_PALETAS = {
    "RdYlGn": ["#a50026", "#d73027", "#f46d43", "#fdae61", "#fee08b", "#ffffbf",
               "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837"],
    "magma": ["#000004", "#1c1044", "#4f127b", "#812581", "#b5367a", "#e55964", "#fb8761",
              "#fec287", "#fcfdbf"],
    "inferno": ["#000004", "#1f0c48", "#550f6d", "#88226a", "#ba3655", "#e35933", "#f98e09",
                "#f9cb35", "#fcffa4"],
}


def _lut(nombre: str, n: int = 256) -> np.ndarray:
    paradas = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in _PALETAS[nombre]], np.float32)
    pos = np.linspace(0, 1, len(paradas))
    t = np.linspace(0, 1, n)
    return np.stack([np.interp(t, pos, paradas[:, k]) for k in range(3)], axis=1).astype(np.uint8)


LUTS = {n: _lut(n) for n in _PALETAS}

# Leyendas en lenguaje sencillo (requisito de usabilidad del prototipo).
LEYENDAS = {
    "rgb": "Color verdadero (bandas B04, B03, B02).",
    "NDVI": "NDVI: vigor de la vegetación. Se satura en dosel denso.",
    "GNDVI": "GNDVI: clorofila. Más sensible que el NDVI en dosel cerrado.",
    "NDRE": "NDRE: clorofila en el borde rojo; valores bajos pueden indicar estrés temprano.",
    "NDMI": "NDMI: agua del dosel; valores bajos pueden indicar estrés hídrico.",
    "evaluable": "Palma evaluable en esta fecha (verde). Blanco: nube o sin dato.",
    "palma_referencia": "Palma de referencia (U-Net, palma en al menos 1/3 de las fechas).",
    "votos": "Cuántos de los 6 detectores marcan el píxel (más claro = más detectores).",
    "consenso": "Anomalía de consenso: la marcan al menos {consenso_min} de los 6 detectores.",
    "persistencia": "Fracción de las fechas del año en que el píxel fue anomalía de consenso.",
    "detector": "Píxeles que marca el detector {detector} (rojo).",
}


def png(rgba: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _rgba(rgb: np.ndarray, alfa: np.ndarray) -> np.ndarray:
    return np.dstack([rgb.astype(np.uint8), (alfa * 255).astype(np.uint8)])


def continua(valores: np.ndarray, mascara: np.ndarray, paleta: str, vmin: float, vmax: float) -> np.ndarray:
    t = np.clip((np.nan_to_num(valores, nan=vmin) - vmin) / (vmax - vmin), 0, 1)
    rgb = LUTS[paleta][(t * 255).astype(np.int32)]
    return _rgba(rgb, mascara.astype(np.float32))


def binaria(mascara: np.ndarray, color, alfa: float = 1.0) -> np.ndarray:
    H, W = mascara.shape
    rgb = np.broadcast_to(np.array(color, np.uint8), (H, W, 3))
    return _rgba(rgb, mascara.astype(np.float32) * alfa)


def capas_escena(rgb, indices, valido, evaluable_t, palma_ref, capas, persistencia, detectores, consenso_min):
    """Todas las capas de una escena -> {nombre: bytes PNG}."""
    # Nube o sin dato: blanco translúcido (en la escena esos píxeles están rellenos con la mediana).
    rgb = np.where(valido[..., None], rgb, 1.0)
    salida = {"rgb": png(_rgba(rgb * 255, np.where(valido, 1.0, 0.7)))}
    for k, nombre in enumerate(["NDVI", "GNDVI", "NDRE", "NDMI"]):
        salida[nombre] = png(continua(indices[k].astype(np.float32), valido, "RdYlGn", -0.2, 1.0))
    ev = binaria(evaluable_t, (34, 197, 94), 0.55)
    nube = ~valido
    ev[nube] = (255, 255, 255, 200)
    salida["evaluable"] = png(ev)
    salida["palma_referencia"] = png(binaria(palma_ref, (34, 197, 94), 0.5))
    votos = capas[-1]
    con_votos = (votos != 255) & (votos > 0)
    salida["votos"] = png(continua(votos.astype(np.float32), con_votos, "magma", 0, len(detectores)))
    salida["consenso"] = png(binaria((votos != 255) & (votos >= consenso_min), (230, 30, 30)))
    salida["persistencia"] = png(continua(persistencia, np.nan_to_num(persistencia) > 0, "inferno", 0, 1))
    for k, m in enumerate(detectores):
        salida[capa_detector(m)] = png(binaria(capas[k] == 1, (230, 30, 30)))
    return salida


def capa_detector(nombre: str) -> str:
    """'One-Class SVM' -> 'det-one-class-svm' (identificador de capa y nombre de archivo)."""
    return "det-" + "-".join(nombre.lower().replace("-", " ").split())
