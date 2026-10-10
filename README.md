# AgroSpec: anomalías espectrales en palma de aceite (Santander)

Objetivo específico 4 del proyecto de grado. Pone el algoritmo de tres módulos al alcance de técnicos de campo
y agrónomos:

- **Módulo 1:** índices NDVI, GNDVI, NDRE y NDMI.
- **Módulo 2:** segmentación de palma con U-Net, palma de referencia y no-dosel persistente.
- **Módulo 3:** seis detectores (One-Class SVM, Isolation Forest, LOF, SimCLR, BYOL y autoencoder) con
  consenso por votos.

> Una anomalía espectral **no es un diagnóstico**. Indica dónde inspeccionar y debe verificarse en campo.

## Interfaz

El diseño sigue el prototipo de Figma "AgroSpec" (paleta verde, tarjetas, navegación inferior en celular), pero
cada pantalla muestra datos reales del backend. Las pantallas del Figma que el algoritmo no respalda (cultivos
distintos de palma, dibujo de polígonos con descarga satelital, recomendaciones de riego) se adaptaron a lo que
el prototipo sí hace.

| Vista | Contenido |
|---|---|
| Ingreso / registro | Cuenta con correo y contraseña (sesión por cookie) |
| Inicio | Plantaciones con la imagen real de su última fecha, semáforo, NDVI, prioridad de visita y mapa general |
| Plantación | Mapa con capas (color verdadero, índices, máscaras, consenso, votos, persistencia, detectores), fechas, evolución del NDVI y del consenso, detectores, detalle de región y de píxel, exportación |
| Nuevo análisis | Carga de una escena (.zip) y progreso real del procesamiento |
| Historial | Todos los análisis, filtrables (con regiones anómalas, cargados por usuarios) |
| Estadísticas | NDVI por tipo de productor, estado de las plantaciones, análisis por mes |
| Perfil | Datos de la cuenta, modo oscuro, estado de los modelos, cierre de sesión |

Es responsive: barra lateral en escritorio (≥ 1024 px), barra inferior en tableta y celular.

**Semáforo** (criterio de presentación, no del algoritmo; `estado_escena` en `backend/app/main.py`):
*sin anomalías* si el consenso no deja regiones del tamaño mínimo; *puntual* si las regiones cubren menos de
`APP_UMBRAL_REVISAR_PCT` (1 %) de la palma evaluable; *revisar en campo* si cubren ese porcentaje o más.

## Arquitectura

```
navegador ──► frontend (React 18 + TypeScript + Vite, React-Leaflet, Recharts; Nginx en Docker)
                 │  /api
                 ▼
              backend (Python 3.11 + FastAPI)
                 ├─ app/pipeline.py   algoritmo portado del notebook (NumPy + ONNX Runtime + scikit-learn)
                 ├─ app/servicio.py   procesamiento por plantación o por fecha nueva, escritura de resultados
                 ├─ app/main.py       API REST; trabajos en segundo plano (BackgroundTasks) con estado en SQLite
                 └─ datos/
                     ├─ modelos/      paquete exportado por el notebook (ONNX + joblib + configuración)
                     ├─ ubicaciones/  palma de referencia, no-dosel y conteos de persistencia por plantación
                     ├─ resultados/   por escena: PNG de capas, anomalias.tif (COG), regiones.geojson, datos.npz
                     └─ app.sqlite3   catálogo, escenas y trabajos
```

| Carpeta | Contenido |
|---|---|
| `Algorithm_Train_...ipynb` | Notebook de entrenamiento (Kaggle, GPU T4) |
| `ml/celda_exportar_app.py` | Celda que se agrega al final del notebook: exporta el paquete de modelos para la app y verifica ONNX contra PyTorch |
| `ml/entrenamiento_demo.py` | Corre el notebook en modo reducido en CPU para obtener un paquete **DEMO** de prueba |
| `backend/` | API, algoritmo portado, precálculo (`scripts/precalcular.py`) y pruebas |
| `frontend/` | Interfaz web |

## API REST

Todas las rutas exigen sesión iniciada (si no, responden 401), excepto `/api/estado` y `/api/auth/*`.

| Método | Ruta | Función |
|---|---|---|
| POST | `/api/auth/registro` | Crea la cuenta (nombre, correo, contraseña ≥ 8, municipio) e inicia sesión |
| POST | `/api/auth/ingreso` | Inicia sesión; deja la cookie `sesion` (HttpOnly, SameSite=Lax) |
| POST | `/api/auth/salida` | Cierra la sesión |
| GET | `/api/auth/yo` | Usuario de la sesión actual |
| GET | `/api/estado` | Modelos cargados, si son DEMO, versiones y verificación ONNX |
| GET | `/api/ubicaciones` | Catálogo: identificador, clase, área, recuadro y resumen de la fecha más reciente |
| GET | `/api/ubicaciones/{id}/fechas` | Fechas disponibles, % de palma evaluable, hectáreas de consenso, NDVI y semáforo |
| GET | `/api/escenas?limite=&desde=&solo=` | Historial de análisis de todas las plantaciones (`solo=anomalia` o `cargadas`) |
| GET | `/api/estadisticas` | Indicadores agregados: NDVI por mes y tipo de productor, estados, análisis por mes |
| GET | `/api/ubicaciones/{id}/resumen.csv` | Resumen por fecha en CSV |
| POST | `/api/escenas` | Carga de una escena (.zip con bandas, `cloud_mask.tif` y `metadata.json`); devuelve un trabajo |
| GET | `/api/trabajos/{id}` | Estado del procesamiento: `en_cola`, `en_proceso`, `terminado` o `error` |
| GET | `/api/escenas/{id}/resumen` | % marcado por cada detector, hectáreas de consenso, regiones y capas |
| GET | `/api/escenas/{id}/capas/{capa}` | PNG de una capa; los límites geográficos van en el resumen y en `X-Limites` |
| GET | `/api/escenas/{id}/regiones` | Regiones anómalas en GeoJSON (`?descargar=true` para descargar) |
| GET | `/api/escenas/{id}/regiones.csv` | Regiones en CSV |
| GET | `/api/escenas/{id}/pixel?lat=&lon=` | Reflectancia de las 10 bandas, índices y puntaje de cada detector |

La documentación interactiva queda en `http://localhost:8000/docs`.

## Puesta en marcha (Windows, desarrollo)

Requisitos: Python 3.11, Node 20 o superior y el dataset de escenas
(`TFG_Sentinel2_Santander/data/mass_dataset_palma_2025_industrial_FINAL_CLEAN`).

### 1. Paquete de modelos

**Corrida definitiva (para la tesis).** En Kaggle, agregue el contenido de `ml/celda_exportar_app.py` como la
última celda del notebook y ejecútelo completo. Descargue `salidas/app_bundle.zip` y descomprímalo en
`backend/datos/modelos/`. La celda también escribe `verificacion_onnx.json`, con la diferencia máxima entre
PyTorch y ONNX Runtime y la concordancia de las decisiones (el capítulo de resultados pide esas cifras).

**Paquete DEMO (solo para probar la app).** Entrena con 24 plantaciones, pocas épocas y pseudoetiquetas de NDVI.
Tarda unos minutos en CPU:

```powershell
python -m venv --system-site-packages ml\.venv      # reutiliza torch si ya está instalado
ml\.venv\Scripts\python -m pip install torch scikit-learn==1.5.2 pandas matplotlib onnx onnxruntime scipy requests
ml\.venv\Scripts\python ml\entrenamiento_demo.py --datos "..\TFG_Sentinel2_Santander\data\mass_dataset_palma_2025_industrial_FINAL_CLEAN"
Copy-Item -Recurse ml\salidas_demo\app_bundle\* backend\datos\modelos\
```

La interfaz muestra una franja morada mientras el paquete cargado sea DEMO.

### 2. Backend y precálculo (modo exploración)

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

El precálculo tiene dos caminos:

- **Importar las salidas del notebook (recomendado).** Usa las máscaras y anomalías que el notebook ya calculó
  en GPU. Los resultados son idénticos a los de la tesis y tarda unos 2 s por plantación. Descomprima
  `modulo2_mascaras.zip` y `modulo3_anomalias.zip` dentro de la carpeta `salidas` descargada de Kaggle:

  ```powershell
  .venv\Scripts\python -m scripts.precalcular --dataset "..\..\TFG_Sentinel2_Santander\data\mass_dataset_palma_2025_industrial_FINAL_CLEAN" --salidas "C:\ruta\a\salidas"
  ```

- **Calcular todo aquí, en CPU.** Corre la U-Net y los seis detectores con ONNX Runtime. Una plantación
  pequeña tarda unos 5 s por escena; una industrial grande, varios minutos por escena. Use `--limite N`
  para procesar solo N plantaciones:

  ```powershell
  .venv\Scripts\python -m scripts.precalcular --dataset "..\..\TFG_Sentinel2_Santander\data\mass_dataset_palma_2025_industrial_FINAL_CLEAN" --limite 10
  ```

`--omitir-existentes` continúa una corrida interrumpida. Después, inicie la API:

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

### 3. Frontend

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173 (reenvía /api al backend en el puerto 8000)
```

### Docker Compose

Con el paquete de modelos y el precálculo ya en `backend/datos/`:

```powershell
docker compose up --build      # http://localhost:8080
```

## Pruebas

```powershell
cd backend
.venv\Scripts\python -m pytest -q
```

- `tests/test_pipeline.py` prueba el algoritmo portado sin modelos: índices, parches, máscaras, regiones y
  persistencia.
- `tests/test_auth.py` prueba registro, ingreso, cierre de sesión, validaciones y que las rutas de datos
  respondan 401 sin sesión.
- `tests/test_integracion.py` prueba el flujo completo con modelos reales: precálculo, todos los endpoints, la
  carga de una fecha nueva y los errores de entrada (zip inválido, banda faltante, rutas fuera de la carpeta).
  Usa `ml/salidas_demo/app_bundle` y el dataset; si no los encuentra, se omite.

## Decisiones y límites conocidos

- **Fidelidad al notebook.** El backend reproduce los mismos pasos numéricos que el notebook: bandas e índices en
  float16, relleno por reflexión, épsilon de los índices en los parches y umbrales calibrados. Sí cambia la
  precisión de inferencia: el notebook usa fp16 en GPU y la app usa fp32 en CPU. Por eso un píxel que queda justo
  en el umbral puede cambiar de decisión. `verificacion_onnx.json` mide cuántas decisiones cambian.
- **Versión de scikit-learn.** Los `.joblib` solo se cargan de forma fiable con la misma versión con que se
  entrenaron. `configuracion_app.json` guarda esa versión; ajuste `backend/requirements.txt` para que coincida.
- **Fecha nueva.** La fecha se remuestrea a la grilla de la plantación. Si cubre menos del 90 % de su recuadro,
  se rechaza. La palma de referencia y el no-dosel son los del precálculo; no se recalculan con la fecha nueva.
- **Trabajos.** Los trabajos corren con `BackgroundTasks` y su estado se guarda en SQLite. Esto basta para pocos
  usuarios. Si hubiera muchos usuarios simultáneos, la cola (Celery + Redis) sería el primer componente a
  reemplazar. Si el servidor se reinicia, los trabajos en curso quedan marcados como `error`.
- **Cuentas.** Contraseñas con PBKDF2-HMAC-SHA256 (240 000 iteraciones, sal aleatoria); la base solo guarda el
  hash del token de sesión. Todas las cuentas ven el mismo catálogo regional (no hay plantaciones por usuario).
  No hay inicio de sesión con Google (exige credenciales OAuth propias), ni recuperación de contraseña, ni límite
  de intentos. Si publica la app en internet, sírvala con HTTPS y defina `APP_COOKIE_SEGURA=1`.
- **Sin descarga automática desde Copernicus** (fuera del alcance del prototipo): las fechas nuevas se suben
  como .zip.
- **NDVI por fecha.** Es la mediana del NDVI en la palma evaluable. Las escenas guardadas antes de esta columna
  se completan solas al iniciar la API (a partir de `datos.npz`).
- **Consulta de píxel.** Los puntajes de los detectores se recalculan al vuelo para el parche de ese píxel
  (menos de 1 s). Así no se guardan puntajes de escenas completas en disco.
- **Enlace directo.** La URL guarda la plantación y la fecha (`?plantacion=PALMA_0001&escena=...`), para
  compartir una vista.
