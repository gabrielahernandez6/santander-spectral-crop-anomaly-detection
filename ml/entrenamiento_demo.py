"""Corre el notebook de entrenamiento en modo REDUCIDO (CPU, pocas ubicaciones y épocas) y exporta un
paquete de modelos DEMO para desarrollar y probar el prototipo sin esperar la corrida completa en Kaggle.

Los modelos resultantes tienen la arquitectura, la normalización y la calibración del notebook, pero están
poco entrenados y usan pseudoetiquetas de NDVI en lugar de GlobalOilPalm. NO sirven para los resultados de
la tesis: para eso se usa el paquete que genera celda_exportar_app.py en la corrida completa.

Uso:
    python ml/entrenamiento_demo.py --datos <carpeta con las escenas> --salida ml/salidas_demo
"""
import argparse
import json
import os
import re
import sys
import types
from pathlib import Path

AQUI = Path(__file__).resolve().parent
NOTEBOOK = AQUI.parent / "Algorithm_Train_Hyperspectral_Imaging_Anomlies_Detection.ipynb"

# Variable -> valor reducido. Se reemplaza la asignación en el código del notebook.
REDUCCION = {
    "N_UBICACIONES_MAX": "24",
    "EPOCAS_SEG": "3", "PASOS_EPOCA_SEG": "15",
    "N_PARCHES_ENTRENAMIENTO": "6000", "N_REFERENCIA": "3000", "N_REFERENCIA_OCSVM": "2000",
    "N_CALIBRACION": "4000", "N_EVALUACION": "1500",
    "EPOCAS_SSL": "3", "EPOCAS_WARMUP_SSL": "1", "BATCH_SIZE_SSL": "256", "EPOCAS_AE": "3",
    "LOTE_INFERENCIA": "4096",
    "GUARDAR_INDICES_TIF": "False", "COMPRIMIR_SALIDAS": "False",
    # La inferencia de los seis detectores en CPU es lenta: mapas solo de las ubicaciones de test.
    "INFERENCIA_SOLO_TEST": "True",
}


def reemplazar(codigo, nombre, valor):
    """Reemplaza 'NOMBRE = ...' aunque esté en una asignación múltiple ('A, B = 1, 2')."""
    patron = re.compile(rf"^(?P<izq>[A-Z_, ]*\b{nombre}\b[A-Z_, ]*)=(?P<der>[^#\n]*)", re.M)
    m = patron.search(codigo)
    if not m:
        return codigo
    nombres = [n.strip() for n in m.group("izq").split(",")]
    valores = [v.strip() for v in re.split(r",(?![^()]*\))", m.group("der"))]
    if len(nombres) != len(valores):
        return codigo
    valores[nombres.index(nombre)] = valor
    nuevo = f"{', '.join(nombres)} = {', '.join(valores)}"
    return codigo[:m.start()] + nuevo + codigo[m.end():]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", required=True, help="carpeta con las escenas (se buscan metadata.json)")
    ap.add_argument("--salida", default=str(AQUI / "salidas_demo"))
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.show = lambda *a, **k: plt.close("all")

    # Sin Earth Engine: iniciar_gee() falla y el notebook usa las pseudoetiquetas de NDVI.
    ee = types.ModuleType("ee")
    def _sin_gee(*a, **k):
        raise RuntimeError("Earth Engine deshabilitado en el modo demo")
    ee.Initialize = ee.Authenticate = _sin_gee
    sys.modules["ee"] = ee

    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    celdas = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    celdas.append((AQUI / "celda_exportar_app.py").read_text(encoding="utf-8"))

    ns = {"__name__": "__main__", "display": lambda *a, **k: [print(x) for x in a], "ES_DEMO": True}
    for k, codigo in enumerate(celdas):
        # Sin '!pip' ni IPython: fuera de Jupyter, display() imprime (se define en ns).
        codigo = "\n".join(l for l in codigo.splitlines()
                           if not l.lstrip().startswith("!") and "from IPython" not in l)
        codigo = reemplazar(codigo, "DATA_ROOT", repr(str(Path(args.datos).resolve())))
        codigo = reemplazar(codigo, "OUT_DIR", repr(str(Path(args.salida).resolve())))
        for nombre, valor in REDUCCION.items():
            codigo = reemplazar(codigo, nombre, valor)
        print(f"\n===== celda de código {k + 1}/{len(celdas)} =====", flush=True)
        exec(compile(codigo, f"<celda {k + 1}>", "exec"), ns)
    print("\nPaquete DEMO en", Path(args.salida) / "app_bundle")


if __name__ == "__main__":
    main()
