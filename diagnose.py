"""
diagnose.py
===========
Script de diagnóstico rápido (NO descarga nada).

Responde:
  1. ¿Archivos clave existen?
  2. ¿config.yaml se carga?
  3. ¿Credenciales OK?
  4. ¿Token OAuth (si hubiese internet)?
  5. ¿AOI palma_santander.geojson?
  6. ¿Catalog API funciona (si tuviera internet)?

Soporta fallos de red sin abortar y muestra claramente las secciones afectadas.
"""
from __future__ import annotations

import logging
import socket
import sys
from pathlib import Path
from typing import Callable


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-7s %(name)s :: %(message)s",
)
logger = logging.getLogger("DIAG")


STEP_HEADER = "+------+--------------------------------------------------------"


def step(n: int, title: str) -> None:
    print()
    print(STEP_HEADER)
    print(f"| [{n:02d}] | {title}")
    print(STEP_HEADER)


def section_ok(msg: str) -> None:
    print(f"  [OK ] {msg}")


def section_warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def section_err(msg: str) -> None:
    print(f"  [ERR] {msg}")


def _try(name: str, fn: Callable, fallback_return=None):
    """Ejecuta fn sin lanzar excepciones. Devuelve (ok, resultado)."""
    try:
        return True, fn()
    except Exception as exc:  # noqa: BLE001
        section_err(f"{name}: {type(exc).__name__}: {exc}")
        return False, fallback_return


def main() -> int:
    project_root = Path(__file__).resolve().parent

    # ======================================================================
    step(1, "Estructura de carpetas y archivos clave")
    # ======================================================================
    checks = {
        "root": project_root,
        ".venv": project_root / ".venv",
        ".env": project_root / ".env",
        "config.yaml": project_root / "config.yaml",
        "santander.geojson": project_root / "data" / "boundaries" / "santander.geojson",
        "palma dir (609 tif)": project_root / "data" / "palm_map" / "GlobalOilPalm_OP-extent",
        "palma_santander.geojson": project_root / "data" / "aoi" / "palma_santander.geojson",
        "output processed/palma": project_root / "data" / "processed" / "palma",
    }
    n_ok = 0
    for name, path in checks.items():
        exists = path.exists()
        size = "-"
        if exists:
            if path.is_file():
                try:
                    kb = path.stat().st_size / 1024
                    size = f"{kb:.1f} KB" if kb < 1024 else f"{kb/1024:.1f} MB"
                except OSError:
                    pass
            else:
                try:
                    size = f"{len(list(path.iterdir()))} entradas"
                except OSError:
                    pass
        if exists:
            section_ok(f"{name:<28s} {str(path):<70s} {size}")
            n_ok += 1
        else:
            section_err(f"{name:<28s} NO EXISTE -> {path}")
    print(f"  -> {n_ok}/{len(checks)} archivos OK.")

    # ======================================================================
    step(2, "Cargar config.yaml y mostrar parámetros")
    # ======================================================================
    sys.path.insert(0, str(project_root))
    ok, cfg = _try("config", lambda: __import__("src.config", fromlist=["load_config"]).load_config())
    if not ok or cfg is None:
        section_err("config.yaml no pudo cargarse. Aborto diagnóstico estructural.")
        return 2

    print(f"  test_mode                      = {cfg.test_mode}")
    print(f"  estimate_only                  = {cfg.estimate_only}")
    print(f"  temporal.start_date            = {cfg.temporal.start_date}")
    print(f"  temporal.end_date              = {cfg.temporal.end_date}")
    print(f"  temporal.months                = {cfg.temporal.months}")
    print(f"  selector.mode                  = {cfg.selector.mode}  (best_monthly=1/mes  all_usable=todas)")
    print(f"  sentinel.collection            = {cfg.sentinel.collection}")
    print(f"  sentinel.resolution            = {cfg.sentinel.resolution} m")
    print(f"  sentinel.max_cloud_cover       = {cfg.sentinel.max_cloud_cover} %")
    print(f"  sentinel.bands ({len(cfg.sentinel.bands)})              = {', '.join(cfg.sentinel.bands)}")
    print(f"  palm.minimum_area_hectares     = {cfg.palm.minimum_area_hectares}")
    print(f"  output.crop_dir_abs            = {cfg.output.crop_dir_abs}")

    # ======================================================================
    step(3, "Credenciales + token OAuth + resolución DNS host Copernicus")
    # ======================================================================
    ok_cred, (cid, csec) = _try(
        "leer credenciales .env",
        lambda: __import__("src.config", fromlist=["get_sh_credentials"]).get_sh_credentials(),
        (None, None),
    )
    if ok_cred and cid and csec:
        section_ok(f"SH_CLIENT_ID y SH_CLIENT_SECRET presentes (longitudes {len(cid)}/{len(csec)}).")
    else:
        section_err("Faltan credenciales en .env (SH_CLIENT_ID / SH_CLIENT_SECRET).")

    # --- Prueba de DNS (sockets, sin requests ni HTTPS, info muy útil)
    hosts_dns = [
        "identity.dataspace.copernicus.eu",
        "sh.dataspace.copernicus.eu",
        "www.google.com",
    ]
    print()
    print("  DNS check (socket getaddrinfo):")
    dns_ok_all = True
    for host in hosts_dns:
        try:
            infos = socket.getaddrinfo(host, 443)
            ip = infos[0][4][0] if infos else "?"
            section_ok(f"  DNS resolve {host:<45s} -> {ip}")
        except socket.gaierror as exc:
            dns_ok_all = False
            section_err(f"  DNS FAILURE {host:<45s} -> {exc}")

    # Intento de token solo si DNS por lo menos resolvió identity...
    print()
    token_len = 0
    if not dns_ok_all:
        section_warn("Hay fallos de DNS. No se intentará obtener token ni Catalog.")
        section_warn("  (revisa firewall / servidores DNS / proxy corporativo / VPN)")
    else:
        ok_tok, token_len = _try(
            "obtener token OAuth",
            lambda: len(
                __import__("src.auth", fromlist=["get_auth"])
                .get_auth()
                .access_token
            ),
            0,
        )
        if ok_tok and token_len:
            section_ok(f"Token OAuth obtenido correctamente (len={token_len}).")
        else:
            section_err("No se consiguió token OAuth (ver .env y conectividad).")

    # ======================================================================
    step(4, "AOI: palma_santander.geojson y parcela TOP-1")
    # ======================================================================
    gdf_ok = False
    gdf = None
    try:
        from src.aoi_generator import load_aoi_gdf, repair_geometries, get_bbox_wgs84
        gdf_raw = load_aoi_gdf(cfg.palm.output_aoi_abs)
        gdf = repair_geometries(gdf_raw)
        gdf = gdf.sort_values("area_ha", ascending=False).reset_index(drop=True)
        gdf_ok = True
    except Exception as exc:
        section_err(f"Cargar AOI: {type(exc).__name__}: {exc}")
        gdf_ok = False

    if gdf_ok and gdf is not None:
        print(f"  Total polígonos                     = {len(gdf):,}")
        print(f"  Área total (ha)                     = {float(gdf['area_ha'].sum()):,.2f}")
        n_1 = int((gdf["class"] == 1).sum())
        n_2 = int((gdf["class"] == 2).sum())
        area_1 = float(gdf.loc[gdf["class"] == 1, "area_ha"].sum())
        area_2 = float(gdf.loc[gdf["class"] == 2, "area_ha"].sum())
        print(f"  Clase 1 Industrial: #polígonos      = {n_1:,}    Área= {area_1:,.2f} ha")
        print(f"  Clase 2 Smallholder: #polígonos     = {n_2:,}    Área= {area_2:,.2f} ha")
        top = gdf.iloc[0]
        bbox = list(get_bbox_wgs84(top.geometry))
        print()
        section_ok(f"TOP-1 parcela: {top['crop_id']}")
        print(f"    crop_id     = {top['crop_id']}")
        print(f"    class_name  = {top['class_name']}")
        print(f"    area_ha     = {float(top['area_ha']):,.2f}")
        print(f"    bbox WGS84  = {bbox}")

    # ======================================================================
    step(5, "Salida: data/processed/palma (qué hay dentro actualmente)")
    # ======================================================================
    out_dir = cfg.output.crop_dir_abs
    existing = []
    try:
        if out_dir.exists():
            existing = sorted([
                p.name for p in out_dir.iterdir() if p.is_dir()
            ])
    except OSError as exc:
        section_err(f"Iterar {out_dir}: {exc}")
    if not existing:
        section_warn("Ninguna parcela descargada todavía -> normal si no se ha ejecutado main.py.")
    else:
        section_ok(f"Hay {len(existing)} carpetas de parcelas en {out_dir}")
        for pname in existing[:10]:
            pdir = out_dir / pname
            files = sorted(f.name for f in pdir.iterdir() if f.is_file())
            print(f"    - {pname}/  ({len(files)} archivos: {', '.join(files[:6])}{'…' if len(files)>6 else ''})")
        if len(existing) > 10:
            print(f"    …y {len(existing)-10} más.")

    # ======================================================================
    step(6, "Siguiente paso / resumen acciones")
    # ======================================================================
    print()
    if not dns_ok_all:
        section_err("FALLO DNS EN HOSTS COPERNICUS.")
        print()
        print("  Cómo solucionar (ordenados por probabilidad de éxito):")
        print("    1) Si estás en RED UNIVERSITARIA / VPN / EMPRESA con proxy:")
        print("        -> Configura PowerShell con HTTP_PROXY / HTTPS_PROXY y")
        print("           ejecuta de nuevo diagnose.py.")
        print("        EJEMPLO (cambia por tu proxy real):")
        print("          $env:HTTP_PROXY  = 'http://proxy.universidad.edu:8080'")
        print("          $env:HTTPS_PROXY = 'http://proxy.universidad.edu:8080'")
        print("          $env:NO_PROXY    = 'localhost,127.0.0.1,.local'")
        print("          python diagnose.py")
        print()
        print("    2) Cambia DNS a público en tu tarjeta de red:")
        print("        Primario  :  8.8.8.8   (Google)")
        print("        Secundario:  1.1.1.1   (Cloudflare)")
        print("        Limpia caché DNS:")
        print("          ipconfig /flushdns")
        print("        Vuelve a ejecutar diagnose.py.")
        print()
        print("    3) Prueba el endpoint manualmente desde navegador:")
        print("        https://identity.dataspace.copernicus.eu/auth/realms/CDSE/.well-known/openid-configuration")
        print("        Si abre JSON en navegador y Python sigue sin conectar, hay")
        print("        proxy/antivirus haciendo SSL intercept.")
        return 4
    elif token_len:
        section_ok("DNS y OAuth token FUNCIONAN.")
        section_warn("Prueba CATALOG API (solo si tuviste internet y DNS OK):")
        print("        python main.py --estimate    # ← NUEVO MODO: estima dataset SIN descargar imágenes")
        print("        python main.py               # ← 1ª descarga real (1 parcela × 1 mes)")
    else:
        section_warn("DNS funciona pero no hay token. Revisa credenciales en .env.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
