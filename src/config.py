"""
config.py
=========
Carga centralizada de parámetros desde config.yaml.
No toca código cada vez que se quiera cambiar un valor.
"""
import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

import yaml
from dotenv import load_dotenv


load_dotenv()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT: Path = _project_root()
DEFAULT_CONFIG_PATH: Path = PROJECT_ROOT / "config.yaml"


@dataclass
class StudyAreaConfig:
    name: str
    country: str
    boundary_path: str

    @property
    def boundary_abs(self) -> Path:
        p = Path(self.boundary_path)
        return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass
class SentinelConfig:
    collection: str
    max_cloud_cover: float
    resolution: int
    bands: List[str] = field(default_factory=list)


@dataclass
class TemporalConfig:
    start_date: str
    end_date: str
    months: int


@dataclass
class SelectorConfig:
    mode: str = "best_monthly"                 # best_monthly | all_usable
    min_days_between: int = 1


@dataclass
class PalmConfig:
    classes: List[int]
    minimum_area_hectares: float
    map_dir: str
    output_aoi: str
    map_zip_path: Optional[str] = None

    @property
    def map_dir_abs(self) -> Path:
        p = Path(self.map_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def map_zip_abs(self) -> Optional[Path]:
        if not self.map_zip_path:
            return None
        p = Path(self.map_zip_path)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def output_aoi_abs(self) -> Path:
        p = Path(self.output_aoi)
        return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass
class CatalogConfig:
    save_responses: bool
    save_dir: str
    limit_per_page: int = 20
    max_pages: int = 50

    @property
    def save_dir_abs(self) -> Path:
        p = Path(self.save_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass
class OutputConfig:
    format: str
    root: str
    crop_type: str

    @property
    def root_abs(self) -> Path:
        p = Path(self.root)
        return p if p.is_absolute() else PROJECT_ROOT / p

    @property
    def crop_dir_abs(self) -> Path:
        return self.root_abs / self.crop_type


@dataclass
class LoggingConfig:
    level: str
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass
class AppConfig:
    test_mode: bool
    estimate_only: bool
    study_area: StudyAreaConfig
    sentinel: SentinelConfig
    temporal: TemporalConfig
    selector: SelectorConfig
    palm: PalmConfig
    catalog: CatalogConfig
    output: OutputConfig
    logging: LoggingConfig
    raw_dir: Path = field(init=False)

    def __post_init__(self):
        self.raw_dir = PROJECT_ROOT / "data" / "raw" / "sentinel2"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.catalog.save_dir_abs.mkdir(parents=True, exist_ok=True)
        self.output.crop_dir_abs.mkdir(parents=True, exist_ok=True)
        self.palm.output_aoi_abs.parent.mkdir(parents=True, exist_ok=True)


def _setup_logging(cfg: LoggingConfig) -> None:
    logging.basicConfig(
        level=getattr(logging, cfg.level.upper(), logging.INFO),
        format=cfg.format,
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    if not config_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    study_area = StudyAreaConfig(**raw.get("study_area", {}))
    sentinel = SentinelConfig(**raw.get("sentinel", {}))
    temporal = TemporalConfig(**raw.get("temporal", {}))
    selector = SelectorConfig(**raw.get("selector", {}))
    palm = PalmConfig(**raw.get("palm", {}))
    catalog = CatalogConfig(**raw.get("catalog", {}))
    output = OutputConfig(**raw.get("output", {}))
    logging_cfg = LoggingConfig(**raw.get("logging", {}))

    cfg = AppConfig(
        test_mode=bool(raw.get("test_mode", True)),
        estimate_only=bool(raw.get("estimate_only", False)),
        study_area=study_area,
        sentinel=sentinel,
        temporal=temporal,
        selector=selector,
        palm=palm,
        catalog=catalog,
        output=output,
        logging=logging_cfg,
    )

    _setup_logging(logging_cfg)
    return cfg


def get_sh_credentials() -> tuple[str, str]:
    client_id = os.getenv("SH_CLIENT_ID")
    client_secret = os.getenv("SH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError(
            "SH_CLIENT_ID y/o SH_CLIENT_SECRET no están definidos en el archivo .env. "
            "Revisa el archivo .env en la raíz del proyecto."
        )
    return client_id, client_secret
