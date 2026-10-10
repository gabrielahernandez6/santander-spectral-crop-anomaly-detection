"""Algoritmo de tres módulos portado del notebook de entrenamiento a NumPy + ONNX Runtime.

Cada función indica la función del notebook que reproduce. Se conservan los mismos detalles numéricos
(bandas e índices guardados en float16, relleno por reflexión, épsilon de los índices en los parches) para
que los umbrales calibrados en el notebook signifiquen lo mismo aquí.
"""
from __future__ import annotations

import json
import math
import os
import re
import warnings
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import onnxruntime as ort
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import array_bounds
from scipy import ndimage

INDICES = ["NDVI", "GNDVI", "NDRE", "NDMI"]
DESCRIPCION_INDICE = {"NDVI": "vigor", "GNDVI": "clorofila", "NDRE": "estrés temprano (red-edge)",
                      "NDMI": "agua del dosel"}
CLASICOS = {"One-Class SVM": "ocsvm", "Isolation Forest": "isolation_forest", "LOF": "lof"}
SSL = {"SimCLR": "encoder_simclr", "BYOL": "encoder_byol"}
PATRON_BANDA = re.compile(r"_B(\d{2}|8A)_", re.I)
LOTE = 4096


class ErrorEscena(ValueError):
    """La escena no se puede procesar (faltan bandas, no coincide con la plantación, etc.)."""


# ------------------------------------------------------------------
# Paquete de modelos
# ------------------------------------------------------------------
class PaqueteModelos:
    """Carga lo que exporta celda_exportar_app.py: redes ONNX, clásicos joblib y configuración."""

    ARCHIVOS = ["configuracion_app.json", "unet.onnx", "encoder_simclr.onnx", "encoder_byol.onnx",
                "autoencoder.onnx", "ocsvm.joblib", "isolation_forest.joblib", "lof.joblib"]

    def __init__(self, carpeta: Path):
        carpeta = Path(carpeta)
        faltan = [a for a in self.ARCHIVOS if not (carpeta / a).exists()]
        if faltan:
            raise FileNotFoundError(f"Faltan archivos del paquete de modelos en {carpeta}: {faltan}")
        self.carpeta = carpeta
        cfg = json.loads((carpeta / "configuracion_app.json").read_text(encoding="utf-8"))
        self.cfg = cfg
        self.bandas: list[str] = cfg["bandas"]
        self.detectores: list[str] = cfg["detectores"]
        self.mu = np.asarray(cfg["media"], np.float32)
        self.sd = np.asarray(cfg["desviacion"], np.float32)
        self.umbrales = {m: float(v) for m, v in cfg["umbrales"].items()}
        self.consenso_min = int(cfg["consenso_min"])
        self.patch = int(cfg["patch"])
        self.r = self.patch // 2
        self.ib = {n: k for k, n in enumerate(self.bandas)}
        self.demo = bool(cfg.get("entrenamiento", {}).get("demo", False))

        opciones = ort.SessionOptions()
        opciones.intra_op_num_threads = int(os.environ.get("APP_HILOS_ONNX", "0"))
        self.redes = {n: ort.InferenceSession(str(carpeta / f"{n}.onnx"), opciones,
                                              providers=["CPUExecutionProvider"])
                      for n in ("unet", "encoder_simclr", "encoder_byol", "autoencoder")}
        with warnings.catch_warnings(record=True) as avisos:
            warnings.simplefilter("always")
            self.clasicos = {m: joblib.load(carpeta / f"{a}.joblib") for m, a in CLASICOS.items()}
        self.avisos = sorted({str(a.message).split("\n")[0] for a in avisos})
        self.ssd = {m: (np.asarray(p["medias"], np.float32), np.asarray(p["precisiones"], np.float32))
                    for m, p in cfg["ssd"].items()}
        verif = carpeta / "verificacion_onnx.json"
        self.verificacion = json.loads(verif.read_text(encoding="utf-8")) if verif.exists() else None

    def info(self) -> dict:
        return dict(demo=self.demo, detectores=self.detectores, umbrales=self.umbrales,
                    consenso_min=self.consenso_min, versiones=self.cfg.get("versiones", {}),
                    entrenamiento=self.cfg.get("entrenamiento", {}), verificacion=self.verificacion,
                    avisos=self.avisos)


# ------------------------------------------------------------------
# Módulo 1: lectura e índices
# ------------------------------------------------------------------
def archivos_bandas(carpeta: Path) -> dict[str, Path]:
    """_archivos_bandas() del notebook."""
    archivos = {}
    for f in os.listdir(carpeta):
        m = PATRON_BANDA.search(f)
        if m and f.lower().endswith((".tif", ".tiff")):
            archivos["B" + m.group(1).upper()] = Path(carpeta) / f
    return archivos


def leer_escena(carpeta: Path, bandas: list[str], forma=None, valor_limpio: int = 1):
    """leer_escena() del notebook: (10, H, W) float32, máscara de válidos, transform y CRS."""
    archivos = archivos_bandas(carpeta)
    faltan = [b for b in bandas if b not in archivos]
    if faltan:
        raise ErrorEscena(f"faltan bandas {faltan}")
    with rasterio.open(archivos["B04"]) as ref:
        transform, crs = ref.transform, ref.crs
        if forma is None:
            forma = (ref.height, ref.width)
    capas = []
    for b in bandas:
        with rasterio.open(archivos[b]) as src:
            a = src.read(1, out_shape=forma, resampling=Resampling.bilinear).astype(np.float32)
            if src.nodata is not None and np.isfinite(src.nodata):
                a[a == src.nodata] = np.nan
        capas.append(a)
    x = np.stack(capas)
    if np.nanmax(x) > 2:                       # escena en DN (x10000)
        x /= 10000.0
    ruta_nube = Path(carpeta) / "cloud_mask.tif"
    if ruta_nube.exists():
        with rasterio.open(ruta_nube) as src:
            limpio = src.read(1, out_shape=forma, resampling=Resampling.nearest) == valor_limpio
    else:
        limpio = np.ones(forma, bool)
    valido = limpio & np.isfinite(x).all(axis=0) & ((x[bandas.index("B08")] + x[bandas.index("B04")]) > 0)
    return x, valido, transform, crs


def _nd(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (a - b) / (a + b)
    return np.clip(np.where(np.isfinite(r), r, 0.0), -1, 1)


def calcular_indices(x: np.ndarray, bandas: list[str]) -> np.ndarray:
    """MÓDULO 1 (calcular_indices del notebook): NDVI, GNDVI, NDRE, NDMI -> (4, H, W)."""
    b = {n: x[k] for k, n in enumerate(bandas)}
    return np.stack([_nd(b["B08"], b["B04"]), _nd(b["B08"], b["B03"]),
                     _nd(b["B08"], b["B05"]), _nd(b["B08"], b["B11"])]).astype(np.float32)


@dataclass
class Escena:
    fecha: str
    bandas: np.ndarray       # (10, H, W) float16, inválidos rellenos con la mediana
    indices: np.ndarray      # (4, H, W) float16
    valido: np.ndarray       # (H, W) bool
    nube: float | None = None


def preparar_escena(x: np.ndarray, valido: np.ndarray, bandas: list[str], fecha: str, nube=None) -> Escena:
    """Paso de cargar_ubicacion(): relleno con la mediana y almacenamiento en float16."""
    if not valido.any():
        raise ErrorEscena("la escena no tiene píxeles válidos (todo nube o sin dato)")
    mediana = np.nanmedian(np.where(valido, x, np.nan).reshape(len(bandas), -1), axis=1)
    x = x.copy()
    x[:, ~valido] = mediana[:, None]
    return Escena(fecha, x.astype(np.float16), calcular_indices(x, bandas).astype(np.float16), valido, nube)


def area_pixel_ha(transform, crs, H, W) -> float:
    """area_pixel_ha() del notebook."""
    if crs is not None and crs.is_geographic:
        _, sur, _, norte = array_bounds(H, W, transform)
        lat = (sur + norte) / 2
        return abs(transform.a) * 111320 * math.cos(math.radians(lat)) * abs(transform.e) * 110574 / 1e4
    return abs(transform.a * transform.e) / 1e4


def rgb_escena(e: Escena, bandas: list[str]) -> np.ndarray:
    """rgb_escena() del notebook: (H, W, 3) en 0-1 con estiramiento 2-98 %."""
    x = e.bandas[[bandas.index("B04"), bandas.index("B03"), bandas.index("B02")]].astype(np.float32)
    lo, hi = np.percentile(x[:, e.valido], [2, 98], axis=1)
    return np.clip((x - lo[:, None, None]) / (hi - lo + 1e-6)[:, None, None], 0, 1).transpose(1, 2, 0)


# ------------------------------------------------------------------
# Módulo 2: segmentación y máscaras
# ------------------------------------------------------------------
def cubo_norm(p: PaqueteModelos, e: Escena) -> np.ndarray:
    x = np.concatenate([e.bandas, e.indices]).astype(np.float32)
    return (x - p.mu[:, None, None]) / p.sd[:, None, None]


def prob_palma(p: PaqueteModelos, e: Escena) -> np.ndarray:
    """prob_palma() del notebook: la U-Net sobre la escena completa con relleno a múltiplo de 8."""
    x = cubo_norm(p, e)
    H, W = x.shape[1:]
    x = np.pad(x, ((0, 0), (0, (-H) % 8), (0, (-W) % 8)), mode="reflect")[None]
    logits = p.redes["unet"].run(None, {"x": np.ascontiguousarray(x)})[0]
    return (1 / (1 + np.exp(-logits[0, :H, :W]))).astype(np.float32)


def mascaras_ubicacion(palma_t: np.ndarray, valido: np.ndarray, ndvi: np.ndarray, cfg: dict):
    """generar_mascaras() del notebook: palma de referencia y no-dosel persistente."""
    n_valid = valido.sum(0)
    palma_ref = (palma_t.sum(0) >= cfg["frac_fechas_palma"] * n_valid) & (n_valid > 0)
    bajo = ((ndvi < cfg["ndvi_no_dosel"]) & valido).sum(0)
    no_dosel = (n_valid >= cfg["min_fechas_temporal"]) & (bajo >= cfg["frac_no_dosel"] * n_valid)
    return palma_ref, no_dosel


def evaluable(palma_ref, no_dosel, valido_t, buffer_px: int) -> np.ndarray:
    cerca_nube = ~valido_t
    if buffer_px:
        cerca_nube = ndimage.binary_dilation(cerca_nube, structure=np.ones((3, 3), bool), iterations=buffer_px)
    return palma_ref & ~no_dosel & ~cerca_nube


# ------------------------------------------------------------------
# Módulo 3: detectores
# ------------------------------------------------------------------
def canales(p: PaqueteModelos, x: np.ndarray) -> np.ndarray:
    """canales() del notebook: parches de reflectancia (N, 10, P, P) -> {X, índices} normalizado."""
    b = lambda n: x[:, p.ib[n]]
    nd = lambda a, c: np.clip((a - c) / (a + c + 1e-6), -1, 1)
    idx = np.stack([nd(b("B08"), b("B04")), nd(b("B08"), b("B03")),
                    nd(b("B08"), b("B05")), nd(b("B08"), b("B11"))], axis=1)
    return ((np.concatenate([x, idx], axis=1) - p.mu[None, :, None, None]) / p.sd[None, :, None, None]
            ).astype(np.float32)


def recortar(xpad: np.ndarray, i: np.ndarray, j: np.ndarray, patch: int) -> np.ndarray:
    """recortar() del notebook: parches (N, 10, P, P) centrados en (i, j) de la escena original."""
    off = np.arange(patch)
    fil = (i[:, None] + off)[:, :, None]
    col = (j[:, None] + off)[:, None, :]
    return xpad[:, fil, col].transpose(1, 0, 2, 3)


def _normalizar(h):
    return h / np.maximum(np.linalg.norm(h, axis=1, keepdims=True), 1e-12)


def puntuar_lote(p: PaqueteModelos, x: np.ndarray) -> dict[str, np.ndarray]:
    """puntuar_lote() del notebook: más alto = más anómalo."""
    r = p.r
    centro = x[:, :, r, r].astype(np.float64)
    salida = {}
    for m in p.detectores:
        if m in CLASICOS:
            salida[m] = -p.clasicos[m].score_samples(centro)
        elif m in SSL:
            h = _normalizar(p.redes[SSL[m]].run(None, {"x": x})[0])
            medias, prec = p.ssd[m]
            dif = h[:, None, :] - medias[None]
            salida[m] = np.einsum("bkd,kde,bke->bk", dif, prec, dif).min(axis=1)
        else:
            rec = p.redes["autoencoder"].run(None, {"x": x})[0]
            salida[m] = ((rec - x)[:, :, r, r] ** 2).mean(1)
    return salida


def detectar_escena(p: PaqueteModelos, e: Escena, evaluable_t: np.ndarray, progreso=None):
    """detectar_escena() del notebook.

    Devuelve capas (7, H, W) uint8 [1 = anómalo, 0 = normal, 255 = no evaluado; la última son los votos]
    y puntajes (6, H, W) float32 (NaN = no evaluado)."""
    H, W = evaluable_t.shape
    nd = len(p.detectores)
    capas = np.full((nd + 1, H, W), 255, np.uint8)
    puntajes = np.full((nd, H, W), np.nan, np.float32)
    ii, jj = np.nonzero(evaluable_t)
    if len(ii) == 0:
        return capas, puntajes
    r = p.r
    xpad = np.pad(e.bandas.astype(np.float32), ((0, 0), (r, r), (r, r)), mode="reflect")
    acum = {m: [] for m in p.detectores}
    for s in range(0, len(ii), LOTE):
        x = canales(p, recortar(xpad, ii[s:s + LOTE], jj[s:s + LOTE], p.patch))
        for m, v in puntuar_lote(p, np.ascontiguousarray(x)).items():
            acum[m].append(v)
        if progreso:
            progreso(min(1.0, (s + LOTE) / len(ii)))
    votos = np.zeros(len(ii), np.uint8)
    for k, m in enumerate(p.detectores):
        s = np.concatenate(acum[m])
        anomalo = s > p.umbrales[m]
        capas[k][ii, jj] = anomalo
        puntajes[k][ii, jj] = s
        votos += anomalo
    capas[-1][ii, jj] = votos
    return capas, puntajes


def consenso(capas: np.ndarray, consenso_min: int):
    votos = capas[-1]
    evaluado = votos != 255
    return evaluado, evaluado & (votos >= consenso_min)


# ------------------------------------------------------------------
# Regiones anómalas
# ------------------------------------------------------------------
def regiones_escena(capas, e: Escena, persistencia, transform, px_ha, consenso_min, area_min_px, bandas):
    """regiones_escena() del notebook, más el polígono y la firma espectral de cada región.

    Devuelve (lista de propiedades, matriz de etiquetas). La firma espectral compara la reflectancia media de
    la región con la mediana de la palma normal (evaluada y sin consenso) de la misma escena."""
    from rasterio import features

    votos = capas[-1]
    evaluado, cons = consenso(capas, consenso_min)
    normal = evaluado & ~cons
    lab = np.zeros(votos.shape, np.int32)
    if not cons.any() or normal.sum() < 30:
        return [], lab
    ind = e.indices.astype(np.float32)
    ref = ind[:, normal]
    med, desv = np.median(ref, axis=1), ref.std(axis=1) + 1e-6
    firma_normal = np.median(e.bandas.astype(np.float32)[:, normal], axis=1)
    etiquetas, _ = ndimage.label(cons, structure=np.ones((3, 3), int))
    salida, nuevo = [], 0
    for k, sl in enumerate(ndimage.find_objects(etiquetas), start=1):
        if sl is None:
            continue
        sel = etiquetas[sl] == k
        n = int(sel.sum())
        if n < area_min_px:
            continue
        nuevo += 1
        lab[sl][sel] = nuevo
        z = (ind[:, sl[0], sl[1]][:, sel].mean(axis=1) - med) / desv
        ys, xs = np.nonzero(sel)
        lon, lat = transform * (xs.mean() + sl[1].start + 0.5, ys.mean() + sl[0].start + 0.5)
        q = int(np.argmin(z))
        firma = e.bandas.astype(np.float32)[:, sl[0], sl[1]][:, sel].mean(axis=1)
        pers = persistencia[sl][sel]
        salida.append(dict(
            region=nuevo, px=n, ha=round(n * px_ha, 3), lon=round(float(lon), 6), lat=round(float(lat), 6),
            votos_medios=round(float(votos[sl][sel].mean()), 2),
            persistencia_media=round(float(np.nanmean(pers)), 2) if np.isfinite(pers).any() else None,
            **{f"z_{nombre}": round(float(z[i]), 2) for i, nombre in enumerate(INDICES)},
            caida_principal=(f"{INDICES[q]} ({DESCRIPCION_INDICE[INDICES[q]]})" if z[q] < -1
                             else "sin caída marcada de índices (anomalía en bandas)"),
            indice_caida=INDICES[q] if z[q] < -1 else None,
            firma={b: round(float(v), 5) for b, v in zip(bandas, firma)},
            firma_normal={b: round(float(v), 5) for b, v in zip(bandas, firma_normal)},
        ))
    geometrias = {}
    for geom, valor in features.shapes(lab, mask=lab > 0, transform=transform, connectivity=8):
        geometrias.setdefault(int(valor), []).append(geom["coordinates"])
    for f in salida:
        poligonos = geometrias.get(f["region"], [])
        f["_geometria"] = ({"type": "Polygon", "coordinates": poligonos[0]} if len(poligonos) == 1
                           else {"type": "MultiPolygon", "coordinates": poligonos})
    return salida, lab


def persistencia(n_consenso: np.ndarray, n_evaluado: np.ndarray) -> np.ndarray:
    """Fracción de fechas evaluadas en que el píxel fue anomalía de consenso (NaN si nunca se evaluó)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n_evaluado > 0, n_consenso / np.maximum(n_evaluado, 1), np.nan).astype(np.float32)
