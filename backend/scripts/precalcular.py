"""Modo exploración: corre el algoritmo completo sobre las plantaciones del dataset y guarda los resultados que
la aplicación muestra. Se ejecuta una vez (o cada vez que cambie el paquete de modelos).

Uso (desde backend/):
    python -m scripts.precalcular --dataset <carpeta con metadata.json>            # todas
    python -m scripts.precalcular --dataset <...> --limite 10                      # prueba rápida
    python -m scripts.precalcular --dataset <...> --ubicaciones PALMA_0001 PALMA_0002
    python -m scripts.precalcular --dataset <...> --salidas <carpeta salidas del notebook>   # recomendado

Sin --salidas, la U-Net y los seis detectores corren aquí, en CPU (del orden de un minuto por escena).
Con --salidas se importan las máscaras y anomalías que el notebook ya calculó en GPU (descomprimir antes
modulo2_mascaras.zip y modulo3_anomalias.zip dentro de esa carpeta): resultados idénticos a la tesis, en segundos.
"""
import argparse
import glob
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, db, servicio  # noqa: E402
from app.pipeline import PaqueteModelos  # noqa: E402


def catalogo(dataset: str, nube_max: float) -> dict[str, dict]:
    """Celda 0.1 del notebook: metadata.json -> escenas utilizables por plantación."""
    filas = []
    for ruta in glob.glob(os.path.join(dataset, "**", "metadata.json"), recursive=True):
        try:
            with open(ruta, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if "crop_id" not in m or "date" not in m or m.get("status", "ok") != "ok":
            continue
        filas.append(dict(crop_id=m["crop_id"], clase=m.get("class_name") or "desconocida",
                          clase_valor=m.get("class_value"), area_ha=m.get("area_ha"), fecha=m["date"],
                          nube=float(m.get("local_cloud_cover_pct") or 0.0), carpeta=os.path.dirname(ruta)))
    mejor = {}
    for f in sorted(filas, key=lambda f: f["nube"]):            # una escena por fecha: la de menos nube
        mejor.setdefault((f["crop_id"], f["fecha"]), f)
    ubic = defaultdict(lambda: dict(escenas=[]))
    for (c, _), f in sorted(mejor.items()):
        if f["nube"] > nube_max:
            continue
        u = ubic[c]
        u.update(crop_id=c, clase=f["clase"], clase_valor=f["clase_valor"], area_ha=f["area_ha"])
        u["escenas"].append(dict(fecha=f["fecha"], carpeta=f["carpeta"], nube=f["nube"]))
    return dict(ubic)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--modelos", default=str(config.MODELOS_DIR))
    ap.add_argument("--limite", type=int, default=None, help="procesar solo las primeras N plantaciones")
    ap.add_argument("--ubicaciones", nargs="*", default=None)
    ap.add_argument("--salidas", default=None, help="carpeta 'salidas' del notebook (importa sus mapas)")
    ap.add_argument("--omitir-existentes", action="store_true", help="no recalcular plantaciones ya guardadas")
    args = ap.parse_args()

    db.iniciar()
    p = PaqueteModelos(Path(args.modelos))
    if p.demo:
        print("AVISO: paquete de modelos DEMO (entrenamiento reducido). No usar para resultados de la tesis.")
    for a in p.avisos:
        print("AVISO al cargar los modelos:", a)
    cat = catalogo(args.dataset, float(p.cfg["nube_max_escena"]))
    ids = sorted(cat)
    if args.ubicaciones:
        ids = [c for c in ids if c in set(args.ubicaciones)]
    if args.limite:
        ids = ids[:args.limite]
    if args.omitir_existentes:
        ids = [c for c in ids if not (config.UBICACIONES_DIR / f"{c}.npz").exists()]
    print(f"{len(cat)} plantaciones en el dataset; se procesan {len(ids)}.")
    split = p.cfg.get("split", {})
    t0, total = time.time(), 0
    for k, c in enumerate(ids, start=1):
        info = dict(cat[c], split=split.get(c, "sin entrenamiento"))
        t1 = time.time()
        n = servicio.procesar_ubicacion(p, info, info["escenas"], salidas=Path(args.salidas) if args.salidas else None)
        total += n
        print(f"[{k}/{len(ids)}] {c}: {n} fechas en {time.time() - t1:.1f} s "
              f"(acumulado {(time.time() - t0) / 60:.1f} min)", flush=True)
    print(f"Listo: {total} escenas de {len(ids)} plantaciones en {(time.time() - t0) / 60:.1f} min.")


if __name__ == "__main__":
    main()
