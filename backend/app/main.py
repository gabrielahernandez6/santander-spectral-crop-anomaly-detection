"""API REST del prototipo (Tabla de recursos de la API en la metodología)."""
from __future__ import annotations

import csv
import io
import re
import shutil
import traceback
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import date

from statistics import median

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, \
    Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import auth, config, db, servicio
from .pipeline import ErrorEscena, PaqueteModelos

ESTADO = {"paquete": None, "error_paquete": None}
ID_VALIDO = re.compile(r"^[A-Za-z0-9_.\-]+$")

# Todas las rutas de datos exigen sesión iniciada; /api/estado y /api/auth/* son públicas.
privado = APIRouter(dependencies=[Depends(auth.usuario_actual)])


@asynccontextmanager
async def _ciclo_de_vida(_app):
    db.iniciar()
    db.marcar_trabajos_interrumpidos()
    servicio.completar_ndvi()
    try:
        ESTADO["paquete"] = PaqueteModelos(config.MODELOS_DIR)
    except Exception as e:                      # el catálogo ya calculado se puede explorar sin modelos
        ESTADO["error_paquete"] = str(e)
    yield


app = FastAPI(title="Anomalías en palma de aceite - Santander", version="1.0.0", lifespan=_ciclo_de_vida,
              description="Prototipo web del algoritmo de detección temprana de anomalías espectrales en "
                          "palma de aceite (Sentinel-2). Una anomalía espectral NO es un diagnóstico.")
app.add_middleware(CORSMiddleware, allow_origins=config.ORIGENES_CORS, allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=True, expose_headers=["Content-Disposition"])


def estado_escena(n_regiones: int | None, pct_consenso: float | None) -> str | None:
    """Semáforo de la interfaz para una fecha. No es un diagnóstico: resume cuánto marcó el consenso.

    sin_anomalias: ninguna región de consenso del tamaño mínimo.
    puntual:       hay regiones, pero cubren menos de UMBRAL_REVISAR_PCT de la palma evaluable.
    revisar:       las regiones cubren UMBRAL_REVISAR_PCT o más; conviene priorizar la visita de campo."""
    if n_regiones is None:
        return None
    if n_regiones == 0:
        return "sin_anomalias"
    return "revisar" if (pct_consenso or 0) >= config.UMBRAL_REVISAR_PCT else "puntual"


# ------------------------------------------------------------------
# Cuentas
# ------------------------------------------------------------------
class Registro(BaseModel):
    nombre: str
    correo: str
    contrasena: str
    municipio: str | None = None


class Ingreso(BaseModel):
    correo: str
    contrasena: str


@app.post("/api/auth/registro", status_code=201)
def registro(datos: Registro, respuesta: Response):
    nombre, correo, municipio = auth.validar_registro(datos.nombre, datos.correo, datos.contrasena, datos.municipio)
    usuario_id = db.crear_usuario(nombre, correo, municipio, auth.hash_contrasena(datos.contrasena))
    if usuario_id is None:
        raise HTTPException(409, "ya existe una cuenta con ese correo")
    auth.abrir_sesion(respuesta, usuario_id)
    return auth.publico(db.usuario_por_correo(correo))


@app.post("/api/auth/ingreso")
def ingreso(datos: Ingreso, respuesta: Response):
    u = db.usuario_por_correo(datos.correo.strip().lower())
    # Mismo mensaje para correo inexistente y contraseña errada: no revela qué correos están registrados.
    if not u or not auth.verificar_contrasena(datos.contrasena, u["hash"]):
        raise HTTPException(401, "correo o contraseña incorrectos")
    auth.abrir_sesion(respuesta, u["id"])
    return auth.publico(u)


@app.post("/api/auth/salida", status_code=204)
def salida(peticion: Request, respuesta: Response):
    auth.cerrar_sesion(peticion, respuesta)
    respuesta.status_code = 204
    return respuesta


@app.get("/api/auth/yo")
def yo(usuario: dict = Depends(auth.usuario_actual)):
    return auth.publico(usuario)


def _paquete() -> PaqueteModelos:
    if ESTADO["paquete"] is None:
        raise HTTPException(503, f"Modelos no cargados: {ESTADO['error_paquete']}")
    return ESTADO["paquete"]


def _id(valor: str) -> str:
    if not ID_VALIDO.match(valor):
        raise HTTPException(400, "identificador inválido")
    return valor


def _escena(escena_id: str) -> dict:
    e = db.escena(_id(escena_id))
    if not e:
        raise HTTPException(404, f"escena {escena_id} no encontrada")
    return e


@app.get("/api/estado")
def estado():
    p = ESTADO["paquete"]
    return dict(modelos_cargados=p is not None, error_modelos=ESTADO["error_paquete"],
                modelos=p.info() if p else None, n_ubicaciones=len(db.ubicaciones()))


@privado.get("/api/ubicaciones")
def ubicaciones():
    return [dict(crop_id=u["crop_id"], clase=u["clase"], area_ha=u["area_ha"], split=u["split"],
                 limites=[[u["sur"], u["oeste"]], [u["norte"], u["este"]]],
                 centro=[(u["sur"] + u["norte"]) / 2, (u["oeste"] + u["este"]) / 2],
                 n_fechas=u["n_fechas"], n_cargadas=u["n_cargadas"], ha_palma_ref=u["ha_palma_ref"],
                 ha_consenso_max=u["ha_consenso_max"],
                 ultima=None if not u["ultima_escena"] else dict(
                     id=u["ultima_escena"], fecha=u["ultima_fecha"], ha_consenso=u["ultima_ha_consenso"],
                     pct_consenso=u["ultima_pct_consenso"], n_regiones=u["ultima_n_regiones"],
                     ndvi_mediana=u["ultima_ndvi"],
                     estado=estado_escena(u["ultima_n_regiones"], u["ultima_pct_consenso"])))
            for u in db.ubicaciones()]


def _con_estado(f: dict) -> dict:
    return dict(f, estado=estado_escena(f["n_regiones"], f["pct_consenso"]))


@privado.get("/api/ubicaciones/{crop_id}/fechas")
def fechas(crop_id: str):
    if not db.ubicacion(_id(crop_id)):
        raise HTTPException(404, f"plantación {crop_id} no encontrada")
    return [_con_estado(f) for f in db.escenas_de(crop_id)]


@privado.get("/api/escenas")
def historial(limite: int = Query(20, ge=1, le=100), desde: int = Query(0, ge=0),
              solo: str | None = Query(None, pattern="^(anomalia|cargadas)$")):
    """Historial de análisis (todas las plantaciones), del más reciente al más antiguo."""
    total, filas = db.escenas_recientes(limite, desde, solo)
    return dict(total=total, escenas=[_con_estado(f) for f in filas])


@privado.get("/api/estadisticas")
def estadisticas():
    """Indicadores agregados del catálogo para la vista de estadísticas."""
    escenas = db.todas_las_escenas()
    ubic = db.ubicaciones()
    ultima: dict[str, dict] = {}
    for e in escenas:                            # ordenadas por fecha: queda la más reciente de cada plantación
        ultima[e["crop_id"]] = e
    estados = {"sin_anomalias": 0, "puntual": 0, "revisar": 0}
    for e in ultima.values():
        estados[estado_escena(e["n_regiones"], e["pct_consenso"])] += 1

    meses: dict[str, dict] = {}
    for e in escenas:
        m = meses.setdefault(e["fecha"][:7], dict(n=0, ha=0.0, ndvi={"industrial": [], "smallholder": []}))
        m["n"] += 1
        m["ha"] += e["ha_consenso"] or 0
        if e["ndvi_mediana"] is not None and e["clase"] in m["ndvi"]:
            m["ndvi"][e["clase"]].append(e["ndvi_mediana"])
    mensual = [dict(mes=k, n_analisis=v["n"], ha_consenso=round(v["ha"], 2),
                    ndvi_industrial=round(median(v["ndvi"]["industrial"]), 4) if v["ndvi"]["industrial"] else None,
                    ndvi_pequeno=round(median(v["ndvi"]["smallholder"]), 4) if v["ndvi"]["smallholder"] else None)
               for k, v in sorted(meses.items())]

    por_clase = []
    for clase in sorted({u["clase"] for u in ubic if u["clase"]}):
        ult = [e for e in ultima.values() if e["clase"] == clase]
        ndvis = [e["ndvi_mediana"] for e in ult if e["ndvi_mediana"] is not None]
        por_clase.append(dict(clase=clase, n_plantaciones=sum(1 for u in ubic if u["clase"] == clase),
                              ndvi_mediana=round(median(ndvis), 4) if ndvis else None,
                              n_revisar=sum(1 for e in ult if estado_escena(e["n_regiones"], e["pct_consenso"])
                                            == "revisar"),
                              ha_consenso=round(sum(e["ha_consenso"] or 0 for e in ult), 2)))
    ndvis = [e["ndvi_mediana"] for e in ultima.values() if e["ndvi_mediana"] is not None]
    return dict(
        n_plantaciones=len(ubic), n_analisis=len(escenas),
        n_cargadas=sum(1 for e in escenas if e["origen"] == "cargada"),
        ha_palma=round(sum(u["ha_palma_ref"] or 0 for u in ubic), 2),
        ha_evaluable_ultima=round(sum(e["ha_evaluable"] or 0 for e in ultima.values()), 2),
        ha_consenso_ultima=round(sum(e["ha_consenso"] or 0 for e in ultima.values()), 2),
        ndvi_mediana_ultima=round(median(ndvis), 4) if ndvis else None,
        estados=estados, mensual=mensual, por_clase=por_clase, umbral_revisar_pct=config.UMBRAL_REVISAR_PCT)


@privado.get("/api/ubicaciones/{crop_id}/resumen.csv")
def resumen_ubicacion_csv(crop_id: str):
    filas = fechas(crop_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["crop_id", "fecha", "origen", "nube_local_pct", "pct_valido", "pct_evaluable", "ha_evaluable",
                "pct_consenso", "ha_consenso", "n_regiones"])
    for f in filas:
        w.writerow([f["crop_id"], f["fecha"], f["origen"], f["nube"], f["pct_valido"], f["pct_evaluable"],
                    f["ha_evaluable"], f["pct_consenso"], f["ha_consenso"], f["n_regiones"]])
    return _descarga(buf.getvalue().encode("utf-8-sig"), f"resumen_{crop_id}.csv", "text/csv")


def _procesar_en_segundo_plano(trabajo_id: str, crop_id: str, carpeta, fecha: str | None):
    escena_id = f"{crop_id}_{fecha or 'nueva'}_{trabajo_id[:8]}"
    try:
        db.actualizar_trabajo(trabajo_id, estado="en_proceso", mensaje="Procesando la escena", progreso=0.0)
        servicio.procesar_escena_nueva(
            _paquete(), crop_id, carpeta, escena_id, fecha,
            lambda f: db.actualizar_trabajo(trabajo_id, progreso=round(f, 3)))
        db.actualizar_trabajo(trabajo_id, estado="terminado", progreso=1.0, escena_id=escena_id,
                              mensaje="Escena procesada")
    except (ErrorEscena, HTTPException) as e:
        db.actualizar_trabajo(trabajo_id, estado="error", mensaje=str(getattr(e, "detail", e)))
    except Exception as e:
        traceback.print_exc()
        db.actualizar_trabajo(trabajo_id, estado="error", mensaje=f"Error interno: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


@privado.post("/api/escenas", status_code=202)
async def cargar_escena(tareas: BackgroundTasks, crop_id: str = Form(...), archivo: UploadFile = File(...),
                        fecha: str | None = Form(None)):
    """Recibe un .zip con las bandas (*_Bxx_*.tif), cloud_mask.tif y, opcionalmente, metadata.json."""
    _paquete()
    if not db.ubicacion(_id(crop_id)):
        raise HTTPException(404, f"plantación {crop_id} no encontrada")
    if fecha:
        try:
            fecha = date.fromisoformat(fecha).isoformat()
        except ValueError:
            raise HTTPException(400, "la fecha debe tener formato AAAA-MM-DD")
    trabajo_id = uuid.uuid4().hex
    carpeta = config.CARGAS_DIR / trabajo_id
    carpeta.mkdir(parents=True)
    contenido = await archivo.read(config.MAX_MB_CARGA * 1024 * 1024 + 1)
    try:
        if len(contenido) > config.MAX_MB_CARGA * 1024 * 1024:
            raise HTTPException(413, f"el archivo supera {config.MAX_MB_CARGA} MB")
        try:
            with zipfile.ZipFile(io.BytesIO(contenido)) as z:
                for nombre in z.namelist():         # evita rutas que escapen de la carpeta (zip slip)
                    destino = (carpeta / nombre).resolve()
                    if not str(destino).startswith(str(carpeta.resolve())):
                        raise HTTPException(400, "el .zip contiene rutas no permitidas")
                z.extractall(carpeta)
        except zipfile.BadZipFile:
            raise HTTPException(400, "el archivo debe ser un .zip con las bandas de la escena")
    except HTTPException:
        shutil.rmtree(carpeta, ignore_errors=True)
        raise
    db.crear_trabajo(trabajo_id, crop_id)
    tareas.add_task(_procesar_en_segundo_plano, trabajo_id, crop_id, carpeta, fecha)
    return {"trabajo_id": trabajo_id}


@privado.get("/api/trabajos/{trabajo_id}")
def trabajo(trabajo_id: str):
    t = db.trabajo(_id(trabajo_id))
    if not t:
        raise HTTPException(404, "trabajo no encontrado")
    return t


@privado.get("/api/escenas/{escena_id}/resumen")
def resumen(escena_id: str):
    return _escena(escena_id)["resumen"]


@privado.get("/api/escenas/{escena_id}/capas/{capa}")
def capa(escena_id: str, capa: str):
    e = _escena(escena_id)
    if capa not in {c["id"] for c in e["resumen"]["capas"]}:
        raise HTTPException(404, f"capa {capa} no existe")
    ruta = servicio.png_capa(escena_id, capa)
    limites = e["resumen"]["limites"]
    return FileResponse(ruta, media_type="image/png",
                        headers={"X-Limites": f"{limites[0][0]},{limites[0][1]},{limites[1][0]},{limites[1][1]}",
                                 "Cache-Control": "max-age=3600"})


@privado.get("/api/escenas/{escena_id}/regiones")
def regiones(escena_id: str, descargar: bool = False):
    _escena(escena_id)
    ruta = servicio.geojson_regiones(escena_id)
    headers = {"Content-Disposition": f'attachment; filename="regiones_{escena_id}.geojson"'} if descargar else {}
    return FileResponse(ruta, media_type="application/geo+json", headers=headers)


@privado.get("/api/escenas/{escena_id}/regiones.csv")
def regiones_csv(escena_id: str):
    import json
    _escena(escena_id)
    geo = json.loads(servicio.geojson_regiones(escena_id).read_text(encoding="utf-8"))
    columnas = ["crop_id", "fecha", "region", "ha", "px", "lat", "lon", "votos_medios", "persistencia_media",
                "z_NDVI", "z_GNDVI", "z_NDRE", "z_NDMI", "caida_principal"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columnas)
    for f in geo["features"]:
        w.writerow([f["properties"].get(c) for c in columnas])
    return _descarga(buf.getvalue().encode("utf-8-sig"), f"regiones_{escena_id}.csv", "text/csv")


@privado.get("/api/escenas/{escena_id}/pixel")
def pixel(escena_id: str, lat: float = Query(...), lon: float = Query(...)):
    _escena(escena_id)
    try:
        return servicio.pixel(_paquete(), escena_id, lat, lon)
    except ErrorEscena as e:
        raise HTTPException(400, str(e))


def _descarga(contenido: bytes, nombre: str, tipo: str) -> Response:
    return Response(contenido, media_type=tipo, headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# Al final: el router se registra después de declarar todas sus rutas.
app.include_router(privado)
