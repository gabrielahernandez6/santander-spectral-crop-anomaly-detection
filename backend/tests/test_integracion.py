"""Flujo completo con modelos reales: precálculo de una plantación, API, consulta de píxel y fecha nueva.

Necesita un paquete de modelos (PRUEBA_MODELOS, por defecto ml/salidas_demo/app_bundle) y el dataset
(PRUEBA_DATASET). Si alguno falta, las pruebas se omiten.
"""
import io
import os
import shutil
import time
import zipfile
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
MODELOS = Path(os.environ.get("PRUEBA_MODELOS", RAIZ / "ml" / "salidas_demo" / "app_bundle"))
DATASET = Path(os.environ.get("PRUEBA_DATASET", RAIZ.parent / "TFG_Sentinel2_Santander" / "data" /
                              "mass_dataset_palma_2025_industrial_FINAL_CLEAN"))

pytestmark = pytest.mark.skipif(not (MODELOS / "configuracion_app.json").exists() or not DATASET.exists(),
                                reason="sin paquete de modelos o sin dataset")


@pytest.fixture(scope="module")
def entorno():
    from app import config
    shutil.copytree(MODELOS, config.MODELOS_DIR, dirs_exist_ok=True)
    from fastapi.testclient import TestClient
    from scripts.precalcular import catalogo
    from app import db, servicio
    from app.pipeline import PaqueteModelos
    db.iniciar()
    p = PaqueteModelos(config.MODELOS_DIR)
    cat = catalogo(str(DATASET), float(p.cfg["nube_max_escena"]))
    # La plantación más pequeña con al menos 3 fechas: el pipeline completo en CPU tarda poco.
    crop_id = min((c for c in cat if len(cat[c]["escenas"]) >= 3), key=lambda c: cat[c]["area_ha"] or 1e9)
    info = dict(cat[crop_id], split="test")
    # Se reservan la última fecha para simular la carga de una fecha nueva.
    t0 = time.time()
    n = servicio.procesar_ubicacion(p, info, info["escenas"][:-1])
    assert n > 0
    print(f"\n{crop_id}: {n} escenas con el pipeline completo en CPU, {(time.time() - t0) / n:.1f} s por escena")
    from app.main import app
    with TestClient(app) as cliente:
        r = cliente.post("/api/auth/registro", json=dict(nombre="Prueba", correo="integracion@ejemplo.com",
                                                         contrasena="clave-segura-1"))
        assert r.status_code == 201, r.text
        yield cliente, crop_id, info["escenas"][-1]


def test_catalogo_y_fechas(entorno):
    c, crop_id, _ = entorno
    est = c.get("/api/estado").json()
    assert est["modelos_cargados"] and est["n_ubicaciones"] == 1
    u = c.get("/api/ubicaciones").json()
    assert u[0]["crop_id"] == crop_id and u[0]["n_fechas"] > 0
    f = c.get(f"/api/ubicaciones/{crop_id}/fechas").json()
    assert all(0 <= x["pct_evaluable"] <= 100 for x in f)
    assert all(x["estado"] in ("sin_anomalias", "puntual", "revisar") for x in f)
    assert all(x["ndvi_mediana"] is None or -1 <= x["ndvi_mediana"] <= 1 for x in f)
    assert u[0]["ultima"]["fecha"] == f[-1]["fecha"]


def test_historial_y_estadisticas(entorno):
    c, crop_id, _ = entorno
    h = c.get("/api/escenas", params=dict(limite=2)).json()
    assert h["total"] >= len(h["escenas"]) and len(h["escenas"]) <= 2
    assert h["escenas"][0]["fecha"] >= h["escenas"][-1]["fecha"] and h["escenas"][0]["clase"]
    assert c.get("/api/escenas", params=dict(solo="otra")).status_code == 422
    e = c.get("/api/estadisticas").json()
    assert e["n_plantaciones"] == 1 and e["n_analisis"] == h["total"]
    assert sum(e["estados"].values()) == 1 and sum(m["n_analisis"] for m in e["mensual"]) == e["n_analisis"]


def test_resumen_capas_regiones_pixel(entorno):
    c, crop_id, _ = entorno
    escena = c.get(f"/api/ubicaciones/{crop_id}/fechas").json()[0]["id"]
    r = c.get(f"/api/escenas/{escena}/resumen").json()
    assert len(r["pct_por_detector"]) == 6 and r["limites"][0][0] < r["limites"][1][0]
    for capa in r["capas"]:
        img = c.get(f"/api/escenas/{escena}/capas/{capa['id']}")
        assert img.status_code == 200 and img.content[:4] == b"\x89PNG", capa["id"]
    assert c.get(f"/api/escenas/{escena}/capas/no-existe").status_code == 404
    g = c.get(f"/api/escenas/{escena}/regiones").json()
    assert g["type"] == "FeatureCollection" and len(g["features"]) == r["n_regiones"]
    (sur, oeste), (norte, este) = r["limites"]
    px = c.get(f"/api/escenas/{escena}/pixel", params=dict(lat=(sur + norte) / 2, lon=(oeste + este) / 2)).json()
    assert len(px["reflectancia"]) == 10 and len(px["detectores"]) == 6
    assert c.get(f"/api/escenas/{escena}/pixel", params=dict(lat=0, lon=0)).status_code == 400
    csv = c.get(f"/api/escenas/{escena}/regiones.csv")
    assert csv.status_code == 200 and csv.text.lstrip("﻿").startswith("crop_id,fecha,region")


def _zip_carpeta(carpeta: Path, sin=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in carpeta.iterdir():
            if f.name not in sin:
                z.write(f, f"escena/{f.name}")
    return buf.getvalue()


def _esperar(c, trabajo_id):
    for _ in range(300):
        t = c.get(f"/api/trabajos/{trabajo_id}").json()
        if t["estado"] in ("terminado", "error"):
            return t
        time.sleep(0.2)
    raise AssertionError("el trabajo no terminó")


def test_fecha_nueva(entorno):
    c, crop_id, reservada = entorno
    resp = c.post("/api/escenas", data={"crop_id": crop_id},
                  files={"archivo": ("escena.zip", _zip_carpeta(Path(reservada["carpeta"])), "application/zip")})
    assert resp.status_code == 202, resp.text
    t = _esperar(c, resp.json()["trabajo_id"])
    assert t["estado"] == "terminado", t["mensaje"]
    fechas = c.get(f"/api/ubicaciones/{crop_id}/fechas").json()
    nueva = [f for f in fechas if f["id"] == t["escena_id"]]
    assert nueva and nueva[0]["origen"] == "cargada" and nueva[0]["fecha"] == reservada["fecha"]


def test_fecha_nueva_errores(entorno):
    c, crop_id, reservada = entorno
    sin_b04 = _zip_carpeta(Path(reservada["carpeta"]), sin={"A_B04_(Raw).tiff"})
    t = _esperar(c, c.post("/api/escenas", data={"crop_id": crop_id},
                           files={"archivo": ("e.zip", sin_b04, "application/zip")}).json()["trabajo_id"])
    assert t["estado"] == "error" and "B04" in t["mensaje"]
    assert c.post("/api/escenas", data={"crop_id": crop_id},
                  files={"archivo": ("e.zip", b"no es zip", "application/zip")}).status_code == 400
    assert c.post("/api/escenas", data={"crop_id": "NO_EXISTE"},
                  files={"archivo": ("e.zip", sin_b04, "application/zip")}).status_code == 404
    assert c.post("/api/escenas", data={"crop_id": crop_id, "fecha": "09/10/2025"},
                  files={"archivo": ("e.zip", sin_b04, "application/zip")}).status_code == 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../../fuera.txt", "x")
    assert c.post("/api/escenas", data={"crop_id": crop_id},
                  files={"archivo": ("e.zip", buf.getvalue(), "application/zip")}).status_code == 400
    assert c.get("/api/escenas/..%2F..%2Fx/resumen").status_code in (400, 404)
