"""Rutas y parámetros del servidor. Todo se puede cambiar con variables de entorno."""
import os
from pathlib import Path

DATOS_DIR = Path(os.environ.get("APP_DATOS", Path(__file__).resolve().parents[1] / "datos"))
MODELOS_DIR = Path(os.environ.get("APP_MODELOS", DATOS_DIR / "modelos"))
RESULTADOS_DIR = DATOS_DIR / "resultados"
UBICACIONES_DIR = DATOS_DIR / "ubicaciones"
CARGAS_DIR = DATOS_DIR / "cargas"
DB_PATH = DATOS_DIR / "app.sqlite3"

MAX_MB_CARGA = int(os.environ.get("APP_MAX_MB_CARGA", "200"))
ORIGENES_CORS = [o for o in os.environ.get("APP_CORS", "http://localhost:5173").split(",") if o]

# Sesiones: duración y si la cookie exige HTTPS (actívelo al publicar la app detrás de HTTPS).
SESION_DIAS = int(os.environ.get("APP_SESION_DIAS", "7"))
COOKIE_SEGURA = os.environ.get("APP_COOKIE_SEGURA", "0") == "1"

# Semáforo de la interfaz: una fecha pasa a "revisar en campo" cuando la anomalía de consenso cubre este
# porcentaje de la palma evaluable o más. Es un criterio de presentación, no un parámetro del algoritmo.
UMBRAL_REVISAR_PCT = float(os.environ.get("APP_UMBRAL_REVISAR_PCT", "1.0"))


def crear_carpetas():
    for d in (DATOS_DIR, MODELOS_DIR, RESULTADOS_DIR, UBICACIONES_DIR, CARGAS_DIR):
        d.mkdir(parents=True, exist_ok=True)
