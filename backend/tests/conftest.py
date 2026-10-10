import os
import sys
import tempfile
from pathlib import Path

# Base de datos y resultados en una carpeta temporal: las pruebas nunca tocan backend/datos.
_TMP = tempfile.mkdtemp(prefix="palma_pruebas_")
os.environ["APP_DATOS"] = _TMP
os.environ.setdefault("APP_MODELOS", str(Path(_TMP) / "modelos"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
