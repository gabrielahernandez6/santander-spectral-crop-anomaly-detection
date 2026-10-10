"""
main.py
=======
Punto de entrada principal del pipeline.

Uso:
  python main.py                       # usa config.yaml raíz
  python main.py mi_config.yaml        # config personalizada
  python main.py --estimate            # equivalente a estimate_only=true

Por defecto (config.yaml) TEST_MODE = true, ESTIMATE_ONLY = false.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


logger = logging.getLogger("main")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _parse_args() -> tuple[str | None, bool]:
    parser = argparse.ArgumentParser(description="Pipeline TFG Sentinel-2 Santander (Palma)")
    parser.add_argument("config", nargs="?", default=None, help="Ruta a config.yaml personalizada")
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Modo estimación (sin descargar imágenes). Equivalente a estimate_only=true en config.yaml.",
    )
    args = parser.parse_args()
    return args.config, args.estimate


def main(argv: list[str] | None = None) -> int:
    _setup_logging()

    # Usamos argparse si nos llaman con lista o desde CLI
    if argv is None:
        config_path_arg, estimate_flag = _parse_args()
    else:
        # Para casos donde se llame main([args...]) de forma programática
        parser = argparse.ArgumentParser()
        parser.add_argument("config", nargs="?", default=None)
        parser.add_argument("--estimate", action="store_true")
        ns = parser.parse_args(argv)
        config_path_arg, estimate_flag = ns.config, ns.estimate

    project_root = Path(__file__).resolve().parent
    sys.path.insert(0, str(project_root))

    config_path: str | None = None
    if config_path_arg:
        p = Path(config_path_arg)
        if not p.exists():
            logger.error("No se encontró el archivo de configuración: %s", p)
            return 1
        config_path = str(p)
    else:
        default = project_root / "config.yaml"
        if not default.exists():
            logger.error("No se encontró config.yaml en la raíz del proyecto.")
            return 1

    from src.config import load_config

    cfg = load_config(config_path)

    # Flag --estimate tiene prioridad
    if estimate_flag:
        cfg.estimate_only = True

    if cfg.estimate_only:
        logger.info("MODO = ESTIMATE_ONLY (sin descargas). Lanzando estimate_dataset...")
        from estimate_dataset import estimate_full
        return estimate_full(config_path)

    # Importación lazy para que el logging setup prevalezca
    from src.pipeline import run_pipeline

    return run_pipeline(config_path)


if __name__ == "__main__":
    raise SystemExit(main())
