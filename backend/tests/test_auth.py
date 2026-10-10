"""Cuentas y sesiones: no necesitan modelos ni dataset."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def cliente():
    from app.main import app
    with TestClient(app) as c:
        yield c


def _registro(c, correo="ana@ejemplo.com", contrasena="clave-segura-1", **extra):
    return c.post("/api/auth/registro", json=dict(nombre="Ana Gómez", correo=correo, contrasena=contrasena,
                                                  municipio="Puerto Wilches", **extra))


def test_rutas_de_datos_exigen_sesion(cliente):
    for ruta in ("/api/ubicaciones", "/api/escenas", "/api/estadisticas", "/api/auth/yo",
                 "/api/escenas/X/capas/rgb", "/api/trabajos/abc"):
        assert cliente.get(ruta).status_code == 401, ruta
    assert cliente.get("/api/estado").status_code == 200


def test_registro_ingreso_y_salida(cliente):
    r = _registro(cliente)
    assert r.status_code == 201 and r.json()["correo"] == "ana@ejemplo.com" and "hash" not in r.json()
    assert "httponly" in r.headers["set-cookie"].lower()
    assert cliente.get("/api/auth/yo").json()["municipio"] == "Puerto Wilches"
    assert cliente.get("/api/ubicaciones").status_code == 200

    assert cliente.post("/api/auth/salida").status_code == 204
    assert cliente.get("/api/auth/yo").status_code == 401

    mal = cliente.post("/api/auth/ingreso", json=dict(correo="ana@ejemplo.com", contrasena="otra-clave-1"))
    nadie = cliente.post("/api/auth/ingreso", json=dict(correo="nadie@ejemplo.com", contrasena="otra-clave-1"))
    assert mal.status_code == nadie.status_code == 401 and mal.json() == nadie.json()

    ok = cliente.post("/api/auth/ingreso", json=dict(correo="  ANA@ejemplo.com ", contrasena="clave-segura-1"))
    assert ok.status_code == 200 and cliente.get("/api/auth/yo").status_code == 200


def test_registro_valida_datos(cliente):
    assert _registro(cliente, correo="b@ejemplo.com", contrasena="corta").status_code == 400
    assert _registro(cliente, correo="no-es-correo").status_code == 400
    assert _registro(cliente, correo="c@ejemplo.com").status_code == 201
    assert _registro(cliente, correo="C@ejemplo.com").status_code == 409


def test_la_base_no_guarda_la_contrasena_ni_el_token():
    from app import auth, db
    db.iniciar()
    h = auth.hash_contrasena("clave-segura-1")
    assert "clave-segura-1" not in h and auth.verificar_contrasena("clave-segura-1", h)
    assert not auth.verificar_contrasena("clave-segura-2", h) and not auth.verificar_contrasena("x", "basura")
    assert auth.hash_contrasena("clave-segura-1") != h          # sal distinta en cada hash
