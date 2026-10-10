"""SQLite: catálogo de plantaciones, escenas procesadas y trabajos en segundo plano."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS ubicaciones (
    crop_id TEXT PRIMARY KEY, clase TEXT, clase_valor INTEGER, area_ha REAL, split TEXT,
    oeste REAL, sur REAL, este REAL, norte REAL, alto INTEGER, ancho INTEGER, px_ha REAL,
    ha_palma_ref REAL
);
CREATE TABLE IF NOT EXISTS escenas (
    id TEXT PRIMARY KEY, crop_id TEXT NOT NULL REFERENCES ubicaciones(crop_id), fecha TEXT NOT NULL,
    origen TEXT NOT NULL, nube REAL, pct_valido REAL, pct_evaluable REAL, ha_evaluable REAL,
    ha_consenso REAL, pct_consenso REAL, n_regiones INTEGER, resumen TEXT, creada REAL
);
CREATE INDEX IF NOT EXISTS escenas_crop ON escenas(crop_id, fecha);
CREATE TABLE IF NOT EXISTS trabajos (
    id TEXT PRIMARY KEY, crop_id TEXT, escena_id TEXT, estado TEXT NOT NULL, progreso REAL DEFAULT 0,
    mensaje TEXT, creado REAL, actualizado REAL
);
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, correo TEXT NOT NULL UNIQUE,
    municipio TEXT, hash TEXT NOT NULL, creado REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sesiones (
    token_hash TEXT PRIMARY KEY, usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    expira REAL NOT NULL
);
"""

# Columnas agregadas después de la primera versión: (tabla, columna, tipo). iniciar() las crea si faltan.
MIGRACIONES = [("escenas", "ndvi_mediana", "REAL")]

_bloqueo = threading.Lock()


@contextmanager
def conexion():
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def iniciar():
    config.crear_carpetas()
    with conexion() as con:
        con.executescript(ESQUEMA)
        con.execute("PRAGMA journal_mode=WAL")
        for tabla, columna, tipo in MIGRACIONES:
            existentes = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
            if columna not in existentes:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def guardar_ubicacion(u: dict):
    with _bloqueo, conexion() as con:
        con.execute("""INSERT OR REPLACE INTO ubicaciones VALUES
            (:crop_id, :clase, :clase_valor, :area_ha, :split, :oeste, :sur, :este, :norte, :alto, :ancho,
             :px_ha, :ha_palma_ref)""", u)


def guardar_escena(e: dict):
    e = dict(e, resumen=json.dumps(e["resumen"], ensure_ascii=False), creada=time.time())
    with _bloqueo, conexion() as con:
        con.execute("""INSERT OR REPLACE INTO escenas
            (id, crop_id, fecha, origen, nube, pct_valido, pct_evaluable, ha_evaluable, ha_consenso, pct_consenso,
             n_regiones, resumen, creada, ndvi_mediana) VALUES
            (:id, :crop_id, :fecha, :origen, :nube, :pct_valido, :pct_evaluable, :ha_evaluable, :ha_consenso,
             :pct_consenso, :n_regiones, :resumen, :creada, :ndvi_mediana)""",
                    dict(e, ndvi_mediana=e.get("ndvi_mediana")))


COLUMNAS_ESCENA = ["id", "crop_id", "fecha", "origen", "nube", "pct_valido", "pct_evaluable", "ha_evaluable",
                   "ha_consenso", "pct_consenso", "n_regiones", "ndvi_mediana"]


def ubicaciones() -> list[dict]:
    """Catálogo con el resumen de la fecha más reciente de cada plantación (la que se muestra en las tarjetas)."""
    with conexion() as con:
        filas = con.execute("""
            WITH ultima AS (
                SELECT crop_id, id, fecha, ha_consenso, pct_consenso, n_regiones, ndvi_mediana,
                       ROW_NUMBER() OVER (PARTITION BY crop_id ORDER BY fecha DESC, creada DESC) AS k
                FROM escenas)
            SELECT u.*, COUNT(e.id) AS n_fechas, MAX(e.ha_consenso) AS ha_consenso_max,
                   SUM(CASE WHEN e.origen = 'cargada' THEN 1 ELSE 0 END) AS n_cargadas,
                   l.id AS ultima_escena, l.fecha AS ultima_fecha, l.ha_consenso AS ultima_ha_consenso,
                   l.pct_consenso AS ultima_pct_consenso, l.n_regiones AS ultima_n_regiones,
                   l.ndvi_mediana AS ultima_ndvi
            FROM ubicaciones u LEFT JOIN escenas e ON e.crop_id = u.crop_id
            LEFT JOIN ultima l ON l.crop_id = u.crop_id AND l.k = 1
            GROUP BY u.crop_id ORDER BY u.crop_id""").fetchall()
    return [dict(f) for f in filas]


def ubicacion(crop_id: str) -> dict | None:
    with conexion() as con:
        f = con.execute("SELECT * FROM ubicaciones WHERE crop_id = ?", (crop_id,)).fetchone()
    return dict(f) if f else None


def escenas_de(crop_id: str) -> list[dict]:
    with conexion() as con:
        filas = con.execute(f"SELECT {', '.join(COLUMNAS_ESCENA)} FROM escenas WHERE crop_id = ? "
                            "ORDER BY fecha, creada", (crop_id,)).fetchall()
    return [dict(f) for f in filas]


def escenas_recientes(limite: int, desplazamiento: int, solo: str | None) -> tuple[int, list[dict]]:
    """Historial de análisis de todas las plantaciones, del más reciente al más antiguo."""
    filtro = {"anomalia": "WHERE e.n_regiones > 0", "cargadas": "WHERE e.origen = 'cargada'"}.get(solo or "", "")
    columnas = ", ".join(f"e.{c}" for c in COLUMNAS_ESCENA)
    with conexion() as con:
        total = con.execute(f"SELECT COUNT(*) FROM escenas e {filtro}").fetchone()[0]
        filas = con.execute(f"""SELECT {columnas}, u.clase FROM escenas e JOIN ubicaciones u ON u.crop_id = e.crop_id
                                {filtro} ORDER BY e.fecha DESC, e.creada DESC LIMIT ? OFFSET ?""",
                            (limite, desplazamiento)).fetchall()
    return total, [dict(f) for f in filas]


def todas_las_escenas() -> list[dict]:
    with conexion() as con:
        filas = con.execute("""SELECT e.crop_id, e.fecha, e.origen, e.ha_consenso, e.pct_consenso, e.n_regiones,
                                      e.ndvi_mediana, e.ha_evaluable, u.clase
                               FROM escenas e JOIN ubicaciones u ON u.crop_id = e.crop_id
                               ORDER BY e.fecha, e.creada""").fetchall()
    return [dict(f) for f in filas]


def escenas_sin_ndvi() -> list[str]:
    with conexion() as con:
        return [f[0] for f in con.execute("SELECT id FROM escenas WHERE ndvi_mediana IS NULL")]


def fijar_ndvi(escena_id: str, valor: float | None):
    with _bloqueo, conexion() as con:
        con.execute("UPDATE escenas SET ndvi_mediana = ? WHERE id = ?", (valor, escena_id))


def escena(escena_id: str) -> dict | None:
    with conexion() as con:
        f = con.execute("SELECT * FROM escenas WHERE id = ?", (escena_id,)).fetchone()
    if not f:
        return None
    d = dict(f)
    d["resumen"] = json.loads(d["resumen"])
    return d


def crear_trabajo(trabajo_id: str, crop_id: str):
    ahora = time.time()
    with _bloqueo, conexion() as con:
        con.execute("INSERT INTO trabajos VALUES (?, ?, NULL, 'en_cola', 0, 'En cola', ?, ?)",
                    (trabajo_id, crop_id, ahora, ahora))


def actualizar_trabajo(trabajo_id: str, **campos):
    campos["actualizado"] = time.time()
    sets = ", ".join(f"{k} = :{k}" for k in campos)
    with _bloqueo, conexion() as con:
        con.execute(f"UPDATE trabajos SET {sets} WHERE id = :id", dict(campos, id=trabajo_id))


def trabajo(trabajo_id: str) -> dict | None:
    with conexion() as con:
        f = con.execute("SELECT * FROM trabajos WHERE id = ?", (trabajo_id,)).fetchone()
    return dict(f) if f else None


def marcar_trabajos_interrumpidos():
    """Al arrancar: un trabajo 'en_proceso' de una ejecución anterior ya no corre."""
    with _bloqueo, conexion() as con:
        con.execute("""UPDATE trabajos SET estado = 'error', mensaje = 'Interrumpido: el servidor se reinició'
                       WHERE estado IN ('en_cola', 'en_proceso')""")


# ------------------------------------------------------------------
# Usuarios y sesiones
# ------------------------------------------------------------------
def crear_usuario(nombre: str, correo: str, municipio: str | None, hash_: str) -> int | None:
    """Devuelve el id nuevo, o None si el correo ya está registrado."""
    try:
        with _bloqueo, conexion() as con:
            cur = con.execute("INSERT INTO usuarios (nombre, correo, municipio, hash, creado) VALUES (?, ?, ?, ?, ?)",
                              (nombre, correo, municipio, hash_, time.time()))
            return int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None


def usuario_por_correo(correo: str) -> dict | None:
    with conexion() as con:
        f = con.execute("SELECT * FROM usuarios WHERE correo = ?", (correo,)).fetchone()
    return dict(f) if f else None


def crear_sesion(token_hash: str, usuario_id: int, expira: float):
    with _bloqueo, conexion() as con:
        con.execute("DELETE FROM sesiones WHERE expira < ?", (time.time(),))
        con.execute("INSERT INTO sesiones VALUES (?, ?, ?)", (token_hash, usuario_id, expira))


def usuario_por_sesion(token_hash: str, ahora: float) -> dict | None:
    with conexion() as con:
        f = con.execute("""SELECT u.* FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id
                           WHERE s.token_hash = ? AND s.expira > ?""", (token_hash, ahora)).fetchone()
    return dict(f) if f else None


def borrar_sesion(token_hash: str):
    with _bloqueo, conexion() as con:
        con.execute("DELETE FROM sesiones WHERE token_hash = ?", (token_hash,))
