"""SOLO LECTURA - Resumen de estado del dataset para TFG.
   3 carpetas:
   1) mass_dataset_palma_2025_industrial_FINAL_CLEAN (nuevo - es el que importa para entrega)
   2) mass_dataset_palma_2025_industrial_bandas_individuales (viejo - con 40% negras)
   3) mass_dataset_palma_2025_industrial (legacy 12bands.tif)
   Outputs: tablas por pantalla.
"""
import sys, csv, json, re
from pathlib import Path
from collections import Counter, defaultdict
# Windows cp1252 safe: activar UTF-8 en stdout para no UnicodeEncodeError
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent / "data"
OUTPUTS = [
    ("(ACTUAL / ENTREGA) mass_dataset_palma_2025_industrial_FINAL_CLEAN ", ROOT / "mass_dataset_palma_2025_industrial_FINAL_CLEAN"),
    ("(VIEJO · ~40% negras) mass_dataset_palma_2025_industrial_bandas_individuales", ROOT / "mass_dataset_palma_2025_industrial_bandas_individuales"),
    ("(LEGACY · 12bands.tif) mass_dataset_palma_2025_industrial", ROOT / "mass_dataset_palma_2025_industrial"),
]

GREEN="\033[92m"; RED="\033[91m"; YEL="\033[93m"; CYN="\033[96m"; MAG="\033[95m"; RST="\033[0m"; BOLD="\033[1m"
MM=[None,"Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]

def _parse_mmdd(name: str):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{6})_", name)
    if not m: return None,None
    return int(m.group(2)), name

# regex para extraer cloud_local_pct del txt too_cloudy
re_cc = re.compile(r"TU PARCELA CONCRETA\s*:\s*([0-9.]+)\s*%")

print(CYN+BOLD+"="*100+RST)
print(CYN+BOLD+f"   RESUMEN EJECUTIVO ESTADO DATASETS (SOLICITUD TFG - {Path(__file__).name})"+RST)
print(CYN+BOLD+"="*100+RST)

for label, path in OUTPUTS:
    exists = path.exists()
    print()
    print(MAG+f"▶ {label}{RST}  |  path = {path}")
    print("─"*100)
    if not exists:
        print(YEL+"   ❌ Carpeta NO existe aún (no has ejecutado la descarga todavía)."+RST)
        continue
    # Carpetas
    folders_all = sorted([d for d in path.iterdir() if d.is_dir()])
    n_f = len(folders_all)

    # Checkpoint si existe
    ok=0; tc=0; err=0; sk=0; clouds_ok=[]; months_ok=Counter(); parcels_ok=defaultdict(set)
    ckpt = path / "checkpoint_download.csv"
    if ckpt.exists():
        # Construir diccionario folder → status/cloud/crop_id para rápido lookup
        folder_info = {}
        with open(ckpt, newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                st = row.get("status","?")
                fol = str(row.get("sample_folder","")).strip()
                cid = str(row.get("crop_id","?")).strip()
                try: c = float(row.get("cloud_local_pct") or -1)
                except: c = -1
                if st=="ok": ok+=1
                elif st=="too_cloudy": tc+=1
                elif st=="error": err+=1
                elif st=="skip_exists": sk+=1
                folder_info[fol] = (st,cid,c)
        # Ahora por carpeta en disco → mes desde nombre (no confiar en CSV month)
        for d in folders_all:
            mm, _ = _parse_mmdd(d.name)
            info = folder_info.get(d.name, ("unknown","?",-1))
            st = info[0]; cid = info[1]; cc = info[2]
            if mm and st=="ok":
                months_ok[mm] += 1
                parcels_ok[cid].add(mm)
                if cc>=0: clouds_ok.append(cc)
    else:
        # fallback - intentar adivinar por metadata
        for d in folders_all:
            mj = d / "metadata.json"
            if mj.exists():
                try:
                    m = json.loads(mj.read_text(encoding="utf-8"))
                    st = m.get("status","?")
                    mm = int(m.get("month",0))
                    cid = str(m.get("crop_id","?"))
                    if st=="ok":
                        ok += 1
                        if mm: months_ok[mm]+=1
                        parcels_ok[cid].add(mm)
                        try: clouds_ok.append(float(m.get("local_cloud_cover_pct",-1)))
                        except: pass
                    else: err+=1
                except: err+=1
            elif (d/"_SKIPPED_TOO_MUCH_CLOUDS.txt").exists():
                tc += 1
                mm,_ = _parse_mmdd(d.name)
                if mm:  # también guardar too_cloudy con mes para distribución
                    pass
            else:
                err += 1

    tot = ok + tc + err + sk
    print(f"   Carpetas en disco              : {n_f:,}")
    print(f"   Filas checkpoint/escaneadas    : {tot:,}")
    print(f"   ✔️  OK 15 archivos (formato LIMP): {GREEN}{ok:>6,}{RST}   ({(ok/tot*100) if tot else 0:.1f}%)")
    print(f"   ⛅  TOO_CLOUDY (solo TXT desc. ): {YEL}{tc:>6,}{RST}   ({(tc/tot*100) if tot else 0:.1f}%)")
    print(f"   ❌  ERROR / pendientes           : {RED}{err:>6,}{RST}")
    if sk: print(f"   ⏭  SKIP ya descargadas prev     : {sk:>6,}")
    if clouds_ok:
        import statistics as st
        print(f"   Nubes medias PARCELA (solo OK) : {GREEN}{sum(clouds_ok)/len(clouds_ok):.1f}% {RST}(mediana {st.median(clouds_ok):.1f}%)")

    print()
    print("   📅 Series temporales OK por MES 2025 (n muestras válidas / mes):")
    print("   ",end="")
    for mm in range(1,13):
        n = months_ok[mm]
        color = GREEN if n>140 else (YEL if n>80 else RED)
        print(f"{color}{MM[mm]:>5s}:{n:>4}{RST}", end="")
        if mm%6==0: print()
    print()
    # Cuántas parcelas con >0, >=6, =12 meses
    n_any = sum(1 for cid,s in parcels_ok.items() if len(s)>0)
    n_6 = sum(1 for cid,s in parcels_ok.items() if len(s)>=6)
    n_12 = sum(1 for cid,s in parcels_ok.items() if len(s)==12)
    # Histograma meses/parcela:
    h = Counter(len(s) for cid,s in parcels_ok.items() if len(s)>0)
    print()
    print(f"   🌴 Cobertura PARCELAS (de 200 top industriales):")
    print(f"      Parcelas con ≥1 mes OK       : {GREEN}{n_any:>4,} / 200  ({n_any/200*100:.0f}%){RST}")
    print(f"      Parcelas con ≥6 meses OK     : {CYN}{n_6:>4,} / 200  ({n_6/200*100:.0f}%){RST}")
    print(f"      Parcelas con 12/12 meses OK  : {MAG}{n_12:>4,} / 200  ({n_12/200*100:.0f}%){RST}")
    if h:
        print()
        print(f"   📊 Histograma: Nº MESES ÚTILES por parcela:")
        for k in sorted(h.keys()):
            bar = "█" * int(h[k])
            print(f"     {k:>2} meses → {h[k]:>4,} parcelas  {GREEN}{bar}{RST}")
        # Parejas consecutivas (medida de continuidad temporal)
        consec=0; totparc=0
        for cid,s in parcels_ok.items():
            if not s: continue
            totparc+=1
            srt=sorted(s)
            for i in range(1,len(srt)):
                if srt[i]==srt[i-1]+1: consec+=1
        print()
        print(f"   🔗 Continuidad temporal: {consec:,} parejas MESES CONSECUTIVOS en {totparc} parcelas ({consec/max(1,totparc):.2f} promedio x parcela)")

print()
print(CYN+BOLD+"="*100+RST)
print(CYN+BOLD+"   CONCLUSIÓN RÁPIDA"+RST)
print(CYN+BOLD+"="*100+RST)
print()
sys.exit(0)
