# ============================================================
# CELDA FINAL DEL NOTEBOOK: paquete de modelos para el prototipo web
# ============================================================
# Pegar como ÚLTIMA celda del notebook de entrenamiento (después de la sección 3.9) y ejecutarla.
# Genera  {OUT_DIR}/app_bundle/  y  {OUT_DIR}/app_bundle.zip  con:
#   unet.onnx, encoder_simclr.onnx, encoder_byol.onnx, autoencoder.onnx   (ONNX, opset 17)
#   ocsvm.joblib, isolation_forest.joblib, lof.joblib                    (scikit-learn)
#   configuracion_app.json   normalización, umbrales, SSD, parámetros del algoritmo, split y versiones
#   verificacion_onnx.json   PyTorch vs ONNX Runtime (Sección "Verificación" de la metodología)
# El prototipo solo necesita esa carpeta: descomprimir app_bundle.zip en backend/datos/modelos/.
try:
    import onnx, onnxruntime as ort
except ImportError:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "onnx", "onnxruntime"], check=True)
    import onnx, onnxruntime as ort
import sklearn

APP_DIR = os.path.join(OUT_DIR, "app_bundle")
os.makedirs(APP_DIR, exist_ok=True)
OPSET = 17


class _SoloReconstruccion(nn.Module):
    """El autoencoder devuelve (reconstrucción, z); el prototipo solo usa la reconstrucción."""
    def __init__(self, ae):
        super().__init__()
        self.ae = ae

    def forward(self, x):
        return self.ae(x)[0]


def _exportar(modelo, ejemplo, ruta, entrada, salida, ejes):
    modelo = copy.deepcopy(modelo).float().cpu().eval()
    kwargs = dict(input_names=[entrada], output_names=[salida], dynamic_axes=ejes, opset_version=OPSET)
    with torch.no_grad():
        try:
            torch.onnx.export(modelo, ejemplo, ruta, dynamo=False, **kwargs)
        except TypeError:                          # versiones de torch sin el argumento 'dynamo'
            torch.onnx.export(modelo, ejemplo, ruta, **kwargs)
    onnx.checker.check_model(onnx.load(ruta))
    return modelo


t0 = time.time()
x_parche = torch.zeros(2, len(CANALES), PATCH, PATCH)
cpu = {
    "unet": _exportar(unet, torch.zeros(1, len(CANALES), 64, 64), os.path.join(APP_DIR, "unet.onnx"),
                      "x", "logits", {"x": {2: "alto", 3: "ancho"}, "logits": {1: "alto", 2: "ancho"}}),
    "encoder_simclr": _exportar(encoder_simclr, x_parche, os.path.join(APP_DIR, "encoder_simclr.onnx"),
                                "x", "h", {"x": {0: "n"}, "h": {0: "n"}}),
    "encoder_byol": _exportar(encoder_byol, x_parche, os.path.join(APP_DIR, "encoder_byol.onnx"),
                              "x", "h", {"x": {0: "n"}, "h": {0: "n"}}),
    "autoencoder": _exportar(_SoloReconstruccion(autoencoder), x_parche, os.path.join(APP_DIR, "autoencoder.onnx"),
                             "x", "reconstruccion", {"x": {0: "n"}, "reconstruccion": {0: "n"}}),
}
for nombre in ("ocsvm", "isolation_forest", "lof"):
    shutil.copy(os.path.join(MODELOS_DIR, f"{nombre}.joblib"), os.path.join(APP_DIR, f"{nombre}.joblib"))
print(f"Modelos exportados en {time.time() - t0:.0f} s")

# ------------------------------------------------------------
# Verificación PyTorch vs ONNX Runtime
# ------------------------------------------------------------
sesiones = {n: ort.InferenceSession(os.path.join(APP_DIR, f"{n}.onnx"), providers=["CPUExecutionProvider"])
            for n in cpu}
N_VERIF = min(4000, len(P_CAL))
with torch.no_grad():
    Xv = canales(P_CAL[:N_VERIF].to(DEVICE)).float().cpu()
dif = {}
for n in ("encoder_simclr", "encoder_byol", "autoencoder"):
    with torch.no_grad():
        ref = cpu[n](Xv).numpy()
    dif[n] = float(np.abs(ref - sesiones[n].run(None, {"x": Xv.numpy()})[0]).max())

# U-Net: probabilidad de palma en escenas completas de validación
dif_unet = 0.0
for c in IDS["val"][:5]:
    u = UBIC[c]
    x = torch.from_numpy(cubo_norm(u, 0))[None]
    x = F.pad(x, (0, (-u["W"]) % 8, 0, (-u["H"]) % 8), mode="reflect")
    with torch.no_grad():
        p_pt = torch.sigmoid(cpu["unet"](x)).numpy()
    p_ort = 1 / (1 + np.exp(-sesiones["unet"].run(None, {"x": x.numpy()})[0]))
    dif_unet = max(dif_unet, float(np.abs(p_pt - p_ort).max()))
dif["unet_probabilidad"] = dif_unet


def _puntajes_ort(x):
    """Mismos puntajes que puntuar_lote(), pero con ONNX Runtime en fp32 (como el prototipo)."""
    xn = x.numpy()
    centro = xn[:, :, R, R].astype(np.float64)
    s = {m: -DETECTORES[m][1].score_samples(centro) for m in ("One-Class SVM", "Isolation Forest", "LOF")}
    for m, n in (("SimCLR", "encoder_simclr"), ("BYOL", "encoder_byol")):
        h = sesiones[n].run(None, {"x": xn})[0]
        h = h / np.maximum(np.linalg.norm(h, axis=1, keepdims=True), 1e-12)
        dd = h[:, None, :] - ssd[m].medias.cpu().numpy()[None]
        s[m] = np.einsum("bkd,kde,bke->bk", dd, ssd[m].precisiones.cpu().numpy(), dd).min(axis=1)
    rec = sesiones["autoencoder"].run(None, {"x": xn})[0]
    s["Autoencoder"] = ((rec - xn)[:, :, R, R] ** 2).mean(1)
    return s


s_nb = {m: [] for m in NOMBRES_DET}
s_ort = {m: [] for m in NOMBRES_DET}
for i in range(0, N_VERIF, 1024):
    for m, v in puntuar_lote(Xv[i:i + 1024].to(DEVICE)).items():   # tal como corre el notebook (fp16 en GPU)
        s_nb[m].append(v)
    for m, v in _puntajes_ort(Xv[i:i + 1024]).items():
        s_ort[m].append(v)
concordancia, dif_puntaje = {}, {}
for m in NOMBRES_DET:
    a, b = np.concatenate(s_nb[m]), np.concatenate(s_ort[m])
    concordancia[m] = float(np.mean((a > UMBRALES[m]) == (b > UMBRALES[m])))
    dif_puntaje[m] = float(np.abs(a - b).max())
verificacion = dict(n_parches=N_VERIF, dif_abs_max_salidas_red_fp32=dif,
                    dif_abs_max_puntajes_vs_notebook=dif_puntaje,
                    concordancia_decisiones_vs_notebook=concordancia,
                    nota="El notebook usa fp16 en GPU para inferencia; ONNX Runtime usa fp32 en CPU. "
                         "dif_abs_max_salidas_red_fp32 compara ambos en fp32 (criterio < 1e-4).")
with open(os.path.join(APP_DIR, "verificacion_onnx.json"), "w") as f:
    json.dump(verificacion, f, indent=2, ensure_ascii=False)
print("Diferencia absoluta máxima (fp32):", {k: f"{v:.2e}" for k, v in dif.items()})
print("Concordancia de decisiones con el notebook:", {k: f"{100 * v:.2f}%" for k, v in concordancia.items()})
if max(dif.values()) >= 1e-4:
    print("⚠️  Alguna salida ONNX difiere >= 1e-4 de PyTorch: revisar antes de usar el prototipo.")

# ------------------------------------------------------------
# Configuración que el prototipo necesita para reproducir la calibración
# ------------------------------------------------------------
config_app = dict(
    version_paquete=1,
    bandas=BANDAS, indices=INDICES, canales=CANALES, media=MU.tolist(), desviacion=SD.tolist(),
    detectores=NOMBRES_DET, umbrales=UMBRALES, contamination=CONTAMINATION, consenso_min=CONSENSO_MIN,
    patch=PATCH, umbral_palma=UMBRAL_PALMA, frac_fechas_palma=FRAC_FECHAS_PALMA,
    ndvi_no_dosel=NDVI_NO_DOSEL, frac_no_dosel=FRAC_NO_DOSEL, min_fechas_temporal=MIN_FECHAS_TEMPORAL,
    buffer_nube_px=BUFFER_NUBE_PX, valor_pixel_limpio=VALOR_PIXEL_LIMPIO, nube_max_escena=NUBE_MAX_ESCENA,
    min_frac_valida=MIN_FRAC_VALIDA, area_min_region_px=AREA_MIN_REGION_PX,
    split={c: u["split"] for c, u in UBIC.items()},
    ssd={n: dict(medias=p.medias.cpu().tolist(), precisiones=p.precisiones.cpu().tolist()) for n, p in ssd.items()},
    versiones=dict(torch=torch.__version__, sklearn=sklearn.__version__, numpy=np.__version__,
                   onnx=onnx.__version__, onnxruntime=ort.__version__),
    entrenamiento=dict(n_ubicaciones=len(UBIC), demo=bool(globals().get("ES_DEMO", False)),
                       fecha=time.strftime("%Y-%m-%d %H:%M")),
)
with open(os.path.join(APP_DIR, "configuracion_app.json"), "w") as f:
    json.dump(config_app, f, ensure_ascii=False)
shutil.make_archive(APP_DIR, "zip", APP_DIR)
print(f"Paquete listo: {APP_DIR}.zip  (scikit-learn {sklearn.__version__}: instalar la MISMA versión en el backend)")
