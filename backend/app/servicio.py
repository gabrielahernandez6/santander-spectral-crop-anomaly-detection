"""Procesamiento completo de una plantación (modo exploración) o de una fecha nueva, y almacenamiento."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine, array_bounds

from . import config, db, render
from .pipeline import (INDICES, Escena, ErrorEscena, PaqueteModelos, area_pixel_ha, canales, consenso,
                       detectar_escena, evaluable, leer_escena, mascaras_ubicacion, persistencia, preparar_escena,
                       prob_palma, puntuar_lote, recortar, regiones_escena, rgb_escena)


def _ruta_escena(escena_id: str) -> Path:
    return config.RESULTADOS_DIR / escena_id


def _ruta_ubicacion(crop_id: str) -> Path:
    return config.UBICACIONES_DIR / f"{crop_id}.npz"


def id_escena(crop_id: str, fecha: str) -> str:
    return f"{crop_id}_{fecha}"


# ------------------------------------------------------------------
# Lectura de lo guardado
# ------------------------------------------------------------------
def cargar_ubicacion(crop_id: str) -> dict:
    ruta = _ruta_ubicacion(crop_id)
    if not ruta.exists():
        raise ErrorEscena(f"la plantación {crop_id} no tiene resultados de referencia; corra el precálculo")
    z = np.load(ruta, allow_pickle=False)
    return dict(palma_ref=z["palma_ref"], no_dosel=z["no_dosel"], n_consenso=z["n_consenso"],
                n_evaluado=z["n_evaluado"], transform=Affine(*z["transform"]), crs=CRS.from_wkt(str(z["crs"])),
                H=int(z["forma"][0]), W=int(z["forma"][1]), px_ha=float(z["px_ha"]))


def cargar_datos_escena(escena_id: str) -> dict:
    ruta = _ruta_escena(escena_id) / "datos.npz"
    if not ruta.exists():
        raise FileNotFoundError(escena_id)
    z = np.load(ruta, allow_pickle=False)
    return {k: z[k] for k in z.files}


def png_capa(escena_id: str, capa: str) -> Path:
    return _ruta_escena(escena_id) / "capas" / f"{capa}.png"


def geojson_regiones(escena_id: str) -> Path:
    return _ruta_escena(escena_id) / "regiones.geojson"


# ------------------------------------------------------------------
# Escritura
# ------------------------------------------------------------------
def _escribir_cog(ruta: Path, arr: np.ndarray, transform, crs, nombres):
    with rasterio.open(ruta, "w", driver="COG", height=arr.shape[1], width=arr.shape[2], count=arr.shape[0],
                       dtype="uint8", crs=crs, transform=transform, nodata=255, compress="DEFLATE") as dst:
        dst.write(arr)
        for k, n in enumerate(nombres, start=1):
            dst.set_band_description(k, n)


def _catalogo_capas(p: PaqueteModelos) -> list[dict]:
    L = render.LEYENDAS
    capas = [dict(id="rgb", nombre="Color verdadero", grupo="base", leyenda=L["rgb"])]
    capas += [dict(id=n, nombre=n, grupo="indice", leyenda=L[n]) for n in INDICES]
    capas += [dict(id="palma_referencia", nombre="Palma de referencia", grupo="mascara",
                   leyenda=L["palma_referencia"]),
              dict(id="evaluable", nombre="Palma evaluable", grupo="mascara", leyenda=L["evaluable"]),
              dict(id="consenso", nombre="Anomalía de consenso", grupo="anomalia",
                   leyenda=L["consenso"].format(consenso_min=p.consenso_min)),
              dict(id="votos", nombre="Votos de los detectores", grupo="anomalia", leyenda=L["votos"]),
              dict(id="persistencia", nombre="Persistencia anual", grupo="anomalia", leyenda=L["persistencia"])]
    capas += [dict(id=render.capa_detector(m), nombre=m, grupo="detector", leyenda=L["detector"].format(detector=m))
              for m in p.detectores]
    return capas


def guardar_escena(p: PaqueteModelos, crop_id: str, escena_id: str, origen: str, e: Escena, ubic: dict,
                   palma_ref, ev, capas, pers):
    """Escribe PNG, GeoTIFF COG, GeoJSON y arreglos de una escena, y la registra en la base de datos."""
    carpeta = _ruta_escena(escena_id)
    if carpeta.exists():
        shutil.rmtree(carpeta)
    (carpeta / "capas").mkdir(parents=True)
    transform, crs, px_ha = ubic["transform"], ubic["crs"], ubic["px_ha"]

    for nombre, contenido in render.capas_escena(rgb_escena(e, p.bandas), e.indices, e.valido, ev, palma_ref,
                                                 capas, pers, p.detectores, p.consenso_min).items():
        (carpeta / "capas" / f"{nombre}.png").write_bytes(contenido)
    _escribir_cog(carpeta / "anomalias.tif", capas, transform, crs, p.detectores + ["votos"])

    regiones, etiquetas = regiones_escena(capas, e, pers, transform, px_ha, p.consenso_min,
                                          int(p.cfg["area_min_region_px"]), p.bandas)
    geo = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": r.pop("_geometria"),
         "properties": dict(r, crop_id=crop_id, fecha=e.fecha, escena_id=escena_id)} for r in regiones]}
    (carpeta / "regiones.geojson").write_text(json.dumps(geo, ensure_ascii=False), encoding="utf-8")

    np.savez_compressed(carpeta / "datos.npz", bandas=e.bandas, indices=e.indices, valido=e.valido,
                        evaluable=ev, capas=capas, persistencia=pers,
                        etiquetas=etiquetas, transform=np.array(transform)[:6])

    evaluado, cons = consenso(capas, p.consenso_min)
    n_ev = int(evaluado.sum())
    ndvi = ndvi_mediana(e.indices, ev)
    oeste, sur, este, norte = array_bounds(ubic["H"], ubic["W"], transform)
    resumen = dict(
        escena_id=escena_id, crop_id=crop_id, fecha=e.fecha, origen=origen, nube=e.nube,
        limites=[[sur, oeste], [norte, este]], alto=ubic["H"], ancho=ubic["W"], px_ha=px_ha,
        pct_valido=round(100 * float(e.valido.mean()), 2),
        px_evaluables=n_ev, ha_evaluable=round(n_ev * px_ha, 2),
        pct_por_detector={m: round(100 * int((capas[k] == 1).sum()) / max(1, n_ev), 3)
                          for k, m in enumerate(p.detectores)},
        pct_consenso=round(100 * int(cons.sum()) / max(1, n_ev), 3),
        ha_consenso=round(int(cons.sum()) * px_ha, 3), n_regiones=len(regiones), ndvi_mediana=ndvi,
        consenso_min=p.consenso_min, umbrales=p.umbrales, demo=p.demo, capas=_catalogo_capas(p),
    )
    db.guardar_escena(dict(id=escena_id, crop_id=crop_id, fecha=e.fecha, origen=origen, nube=e.nube,
                           pct_valido=resumen["pct_valido"], pct_evaluable=round(100 * n_ev / e.valido.size, 2),
                           ha_evaluable=resumen["ha_evaluable"], ha_consenso=resumen["ha_consenso"],
                           pct_consenso=resumen["pct_consenso"], n_regiones=len(regiones), resumen=resumen,
                           ndvi_mediana=ndvi))
    return resumen


def ndvi_mediana(indices: np.ndarray, ev: np.ndarray) -> float | None:
    """Mediana del NDVI en la palma evaluable de la escena (None si no hay palma evaluable)."""
    v = indices[0][ev].astype(np.float32)
    v = v[np.isfinite(v)]
    return round(float(np.median(v)), 4) if v.size else None


def completar_ndvi() -> int:
    """Calcula el NDVI de las escenas guardadas antes de que existiera la columna. Devuelve cuántas completó."""
    n = 0
    for escena_id in db.escenas_sin_ndvi():
        try:
            d = cargar_datos_escena(escena_id)
        except FileNotFoundError:
            continue
        db.fijar_ndvi(escena_id, ndvi_mediana(d["indices"], d["evaluable"]))
        n += 1
    return n


# ------------------------------------------------------------------
# Modo exploración: una plantación completa con todas sus fechas
# ------------------------------------------------------------------
def _leer_tif(ruta: Path, bandas=None) -> np.ndarray:
    with rasterio.open(ruta) as src:
        return src.read(bandas)


def procesar_ubicacion(p: PaqueteModelos, info: dict, escenas: list[dict], progreso=None,
                       salidas: Path | None = None) -> int:
    """info: crop_id, clase, clase_valor, area_ha. escenas: [{fecha, carpeta, nube}] ordenadas por fecha.
    Reproduce cargar_ubicacion() + generar_mascaras() + detectar_escena() + persistencia del notebook.

    Con 'salidas' (carpeta 'salidas' del notebook, con modulo2_mascaras/ y modulo3_anomalias/ descomprimidos) no
    se corren la U-Net ni los detectores: se importan las máscaras y anomalías que el notebook calculó en GPU.
    Así la aplicación muestra exactamente los resultados de la tesis y el precálculo tarda segundos."""
    cfg = p.cfg
    c = info["crop_id"]
    if salidas is not None:
        m2, m3 = Path(salidas) / "modulo2_mascaras" / c, Path(salidas) / "modulo3_anomalias" / c
        if not (m2 / f"{c}_mascaras_ubicacion.tif").exists():
            print(f"  {c}: sin salidas del notebook en {m2}; se omite")
            return 0
        escenas = [f for f in escenas if (m3 / f"{f['fecha']}_anomalias.tif").exists()]
    forma = transform = crs = None
    serie: list[Escena] = []
    for f in escenas:
        try:
            x, valido, tr, cr = leer_escena(Path(f["carpeta"]), p.bandas, forma, cfg["valor_pixel_limpio"])
        except Exception as err:                      # el notebook también omite la fecha y sigue
            print(f"  {info['crop_id']} {f['fecha']}: se omite ({err})")
            continue
        if forma is None:
            forma, transform, crs = x.shape[1:], tr, cr
        if valido.mean() < cfg["min_frac_valida"]:
            continue
        serie.append(preparar_escena(x, valido, p.bandas, f["fecha"], f.get("nube")))
    if not serie:
        return 0
    H, W = forma
    px_ha = area_pixel_ha(transform, crs, H, W)
    if salidas is not None:
        ref = _leer_tif(m2 / f"{c}_mascaras_ubicacion.tif", [1, 2]).astype(bool)
        palma_ref, no_dosel = ref[0], ref[1]
    else:
        valido = np.stack([e.valido for e in serie])
        palma_t = np.stack([(prob_palma(p, e) >= cfg["umbral_palma"]) & e.valido for e in serie])
        ndvi = np.stack([e.indices[0].astype(np.float32) for e in serie])
        palma_ref, no_dosel = mascaras_ubicacion(palma_t, valido, ndvi, cfg)

    resultados = []
    for k, e in enumerate(serie):
        if salidas is not None:
            ev = _leer_tif(m2 / f"{e.fecha}_mascaras.tif", 3).astype(bool)
            capas = _leer_tif(m3 / f"{e.fecha}_anomalias.tif").astype(np.uint8)
            if capas.shape != (len(p.detectores) + 1, H, W):
                raise ErrorEscena(f"{c} {e.fecha}: anomalías del notebook con forma {capas.shape}")
            resultados.append((e, ev, capas, None))
        else:
            ev = evaluable(palma_ref, no_dosel, e.valido, cfg["buffer_nube_px"])
            resultados.append((e, ev, *detectar_escena(p, e, ev)))
        if progreso:
            progreso((k + 1) / (len(serie) + 1))
    n_cons = sum(consenso(c, p.consenso_min)[1].astype(np.int16) for _, _, c, _ in resultados)
    n_ev = sum(consenso(c, p.consenso_min)[0].astype(np.int16) for _, _, c, _ in resultados)
    pers = persistencia(n_cons, n_ev)

    ubic = dict(transform=transform, crs=crs, H=H, W=W, px_ha=px_ha)
    np.savez_compressed(_ruta_ubicacion(info["crop_id"]), palma_ref=palma_ref, no_dosel=no_dosel,
                        n_consenso=n_cons, n_evaluado=n_ev, transform=np.array(transform)[:6],
                        crs=np.array(crs.to_wkt()), forma=np.array([H, W]), px_ha=np.array(px_ha))
    oeste, sur, este, norte = array_bounds(H, W, transform)
    db.guardar_ubicacion(dict(crop_id=info["crop_id"], clase=info.get("clase"), clase_valor=info.get("clase_valor"),
                              area_ha=info.get("area_ha"), split=info.get("split"), oeste=oeste, sur=sur, este=este,
                              norte=norte, alto=H, ancho=W, px_ha=px_ha,
                              ha_palma_ref=round(float(palma_ref.sum()) * px_ha, 2)))
    for e, ev, capas, _ in resultados:
        guardar_escena(p, info["crop_id"], id_escena(info["crop_id"], e.fecha), "catalogo", e, ubic, palma_ref, ev,
                       capas, pers)
    if progreso:
        progreso(1.0)
    return len(resultados)


# ------------------------------------------------------------------
# Modo "fecha nueva": una escena cargada por el usuario
# ------------------------------------------------------------------
def _carpeta_con_bandas(raiz: Path) -> Path:
    for carpeta in [raiz, *sorted(d for d in raiz.rglob("*") if d.is_dir())]:
        if any(f.name.upper().find("_B04_") >= 0 for f in carpeta.iterdir() if f.is_file()):
            return carpeta
    raise ErrorEscena("el archivo no contiene bandas Sentinel-2 con nombres tipo '*_B04_*.tif'")


def _metadata(carpeta: Path) -> dict:
    ruta = carpeta / "metadata.json"
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def procesar_escena_nueva(p: PaqueteModelos, crop_id: str, raiz: Path, escena_id: str, fecha: str | None,
                          progreso=None) -> dict:
    """Reutiliza la palma de referencia y el no-dosel guardados para la plantación (Sección de modos de uso)."""
    cfg = p.cfg
    ubic = cargar_ubicacion(crop_id)
    carpeta = _carpeta_con_bandas(raiz)
    meta = _metadata(carpeta)
    if meta.get("crop_id") and meta["crop_id"] != crop_id:
        raise ErrorEscena(f"la escena es de {meta['crop_id']}, no de {crop_id}")
    fecha = fecha or meta.get("date")
    if not fecha:
        raise ErrorEscena("indique la fecha de la escena (no viene en metadata.json)")

    x, valido, tr, cr = leer_escena(carpeta, p.bandas, (ubic["H"], ubic["W"]), cfg["valor_pixel_limpio"])
    _comprobar_misma_zona(tr, cr, x.shape[1:], ubic)
    if valido.mean() < cfg["min_frac_valida"]:
        raise ErrorEscena(f"solo {100 * valido.mean():.1f}% de píxeles válidos (mínimo "
                          f"{100 * cfg['min_frac_valida']:.0f}%): la escena está casi toda cubierta de nubes")
    if progreso:
        progreso(0.1)
    e = preparar_escena(x, valido, p.bandas, fecha, meta.get("local_cloud_cover_pct"))
    ev = evaluable(ubic["palma_ref"], ubic["no_dosel"], e.valido, cfg["buffer_nube_px"])
    capas, _ = detectar_escena(p, e, ev, (lambda f: progreso(0.1 + 0.8 * f)) if progreso else None)
    evaluado, cons = consenso(capas, p.consenso_min)
    pers = persistencia(ubic["n_consenso"] + cons, ubic["n_evaluado"] + evaluado)
    resumen = guardar_escena(p, crop_id, escena_id, "cargada", e, ubic, ubic["palma_ref"], ev, capas, pers)
    if progreso:
        progreso(1.0)
    return resumen


def _comprobar_misma_zona(transform, crs, forma, ubic):
    """La escena se remuestrea a la grilla de la plantación, así que debe cubrir el mismo recuadro."""
    a = array_bounds(*forma, transform)
    b = array_bounds(ubic["H"], ubic["W"], ubic["transform"])
    if crs != ubic["crs"]:
        raise ErrorEscena(f"la escena está en {crs}, la plantación en {ubic['crs']}")
    inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    if inter < 0.9 * area_b:
        raise ErrorEscena(f"la escena cubre solo {100 * inter / area_b:.0f}% del recuadro de la plantación "
                          "(se necesita al menos 90%)")


def pixel(p: PaqueteModelos, escena_id: str, lat: float, lon: float) -> dict:
    d = cargar_datos_escena(escena_id)
    transform = Affine(*d["transform"])
    col, fila = ~transform * (lon, lat)
    i, j = int(np.floor(fila)), int(np.floor(col))
    H, W = d["valido"].shape
    if not (0 <= i < H and 0 <= j < W):
        raise ErrorEscena("el punto está fuera de la escena")
    votos = int(d["capas"][-1, i, j])
    evaluado = votos != 255
    puntajes = {}
    if evaluado:
        # Se recalcula solo el parche de este píxel: mismo resultado que en el procesamiento, sin guardar
        # los puntajes de toda la escena en disco.
        r = p.r
        xpad = np.pad(d["bandas"].astype(np.float32), ((0, 0), (r, r), (r, r)), mode="reflect")
        x = canales(p, recortar(xpad, np.array([i]), np.array([j]), p.patch))
        puntajes = {m: float(v[0]) for m, v in puntuar_lote(p, np.ascontiguousarray(x)).items()}
    lab = int(d["etiquetas"][i, j])
    return dict(
        fila=i, columna=j, lat=lat, lon=lon, valido=bool(d["valido"][i, j]), evaluable=bool(d["evaluable"][i, j]),
        reflectancia={b: round(float(v), 5) for b, v in zip(p.bandas, d["bandas"][:, i, j].astype(np.float32))},
        indices={n: round(float(v), 4) for n, v in zip(INDICES, d["indices"][:, i, j].astype(np.float32))},
        detectores=[dict(detector=m, puntaje=(round(puntajes[m], 5) if evaluado else None),
                         umbral=round(p.umbrales[m], 5), anomalo=bool(d["capas"][k, i, j] == 1))
                    for k, m in enumerate(p.detectores)],
        votos=votos if evaluado else None, consenso=evaluado and votos >= p.consenso_min,
        persistencia=(None if not np.isfinite(d["persistencia"][i, j]) else round(float(d["persistencia"][i, j]), 3)),
        region=lab or None,
    )
