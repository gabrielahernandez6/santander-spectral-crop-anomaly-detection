"""Cuentas de usuario: registro, inicio de sesión y sesión por cookie.

Contraseñas con PBKDF2-HMAC-SHA256 (biblioteca estándar, sin dependencias nuevas). La sesión es un token
aleatorio en una cookie HttpOnly; en la base de datos solo se guarda su hash SHA-256, así que una copia de la
base no permite suplantar a nadie. La cookie (y no una cabecera Authorization) permite que las imágenes de las
capas y las descargas CSV/GeoJSON, que el navegador pide sin JavaScript, también queden protegidas.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import time

from fastapi import HTTPException, Request, Response

from . import config, db

ITERACIONES = 240_000
COOKIE = "sesion"
CORREO_VALIDO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_contrasena(contrasena: str, sal: bytes | None = None) -> str:
    sal = sal or secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), sal, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal.hex()}${h.hex()}"


def verificar_contrasena(contrasena: str, guardado: str) -> bool:
    try:
        _, iteraciones, sal, esperado = guardado.split("$")
        h = hashlib.pbkdf2_hmac("sha256", contrasena.encode("utf-8"), bytes.fromhex(sal), int(iteraciones))
    except ValueError:
        return False
    return hmac.compare_digest(h.hex(), esperado)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def validar_registro(nombre: str, correo: str, contrasena: str, municipio: str | None) -> tuple[str, str, str | None]:
    nombre, correo = nombre.strip(), correo.strip().lower()
    if not 2 <= len(nombre) <= 80:
        raise HTTPException(400, "el nombre debe tener entre 2 y 80 caracteres")
    if not CORREO_VALIDO.match(correo) or len(correo) > 120:
        raise HTTPException(400, "correo electrónico inválido")
    if len(contrasena) < 8:
        raise HTTPException(400, "la contraseña debe tener al menos 8 caracteres")
    if len(contrasena) > 128:
        raise HTTPException(400, "la contraseña no puede superar 128 caracteres")
    municipio = (municipio or "").strip()[:60] or None
    return nombre, correo, municipio


def abrir_sesion(respuesta: Response, usuario_id: int) -> None:
    token = secrets.token_urlsafe(32)
    expira = time.time() + config.SESION_DIAS * 86400
    db.crear_sesion(_hash_token(token), usuario_id, expira)
    respuesta.set_cookie(COOKIE, token, max_age=config.SESION_DIAS * 86400, httponly=True, samesite="lax",
                         secure=config.COOKIE_SEGURA, path="/")


def cerrar_sesion(peticion: Request, respuesta: Response) -> None:
    token = peticion.cookies.get(COOKIE)
    if token:
        db.borrar_sesion(_hash_token(token))
    respuesta.delete_cookie(COOKIE, path="/")


def usuario_actual(peticion: Request) -> dict:
    """Dependencia de FastAPI: devuelve el usuario de la sesión o responde 401."""
    token = peticion.cookies.get(COOKIE)
    usuario = db.usuario_por_sesion(_hash_token(token), time.time()) if token else None
    if not usuario:
        raise HTTPException(401, "inicie sesión para continuar")
    return usuario


def publico(u: dict) -> dict:
    return dict(id=u["id"], nombre=u["nombre"], correo=u["correo"], municipio=u["municipio"], creado=u["creado"])
