# TFG - Pipeline Sentinel-2 Santander (Palma de Aceite)

> **Título**: *Algoritmo basado en aprendizaje autosupervisado para la detección temprana de anomalías en cultivos agrícolas mediante el análisis de imágenes espectrales en el departamento de Santander*

Este repositorio implementa un **pipeline Python completamente automatizado** que:

1. Detecta automáticamente zonas de **palma de aceite** dentro del departamento de Santander usando el dataset *Global Oil Palm Extent*.
2. Convierte esas zonas en parcelas / AOIs polígonales únicas.
3. Consulta **Copernicus Data Space Ecosystem** mediante **Sentinel Hub Catalog API** para descubrir imágenes Sentinel-2 L2A disponibles.
4. Selecciona, para cada parcela, la **mejor imagen de cada mes** (menor cobertura nubosa).
5. Descarga únicamente el AOI de cada parcela con **Sentinel Hub Process API**, en resolución 10 m y 12 bandas L2A.
6. Genera **máscaras de nubes locales** a partir de SCL (*Scene Classification Layer*).
7. Homogeneiza formato / resolución y guarda **metadata JSON reproducible** por muestra, más un CSV global del dataset.
8. Permite extender el pipeline más adelante a **cacao** y **café**.

---

## Estructura del proyecto

```
TFG_Sentinel2_Santander/
│
├── .venv/                          # Entorno virtual (NO compartir por Git)
│
├── data/
│   ├── palm_map/
│   │   ├── GlobalOilPalm_OP-extent.zip       # Dataset original (NO tocar)
│   │   └── GlobalOilPalm_OP-extent/          # 609 GeoTIFF (descomprimir)
│   │
│   ├── boundaries/
│   │   └── santander.geojson                 # Límite geográfico dept. Santander EPSG:4326
│   │
│   ├── aoi/
│   │   └── palma_santander.geojson           # Salida: 2434 parcelas PALMA_####
│   │
│   ├── catalog/                              # Respuestas JSON opcionales del Catalog API
│   │
│   ├── raw/sentinel2/                        # Datos brutos (por ahora vía Process API)
│   │
│   └── processed/
│       └── palma/
│           ├── PALMA_0001/
│           │   ├── 2025-01.tif               # 12 bandas L2A, 10m, AOI PALMA_0001
│           │   ├── 2025-01_metadata.json     # metadata completa por muestra
│           │   ├── 2025-01_cloud_mask.tif    # máscara válido/inválido/nodata
│           │   └── selections.json           # decisiones del selector mensual
│           ├── PALMA_0002/
│           ├── ...
│           └── dataset_summary.csv           # resumen de TODAS las muestras
│
├── src/
│   ├── __init__.py
│   ├── config.py            # Carga config.yaml y credenciales
│   ├── auth.py              # OAuth2 Copernicus + token cacheado
│   ├── palm_detector.py     # 609 teselas -> palma_santander.geojson
│   ├── aoi_generator.py     # Carga AOI, repara geometrías, bbox, iterador
│   ├── catalog.py           # Sentinel Hub Catalog API (STAC)
│   ├── image_selector.py    # Selección mensual (available/unavailable)
│   ├── downloader.py        # Sentinel Hub Process API + escritura GeoTIFF
│   ├── cloud_mask.py        # SCL -> máscara válido/inválido/nodata
│   ├── preprocessing.py     # Remuestreo a 10m + alineación + validación
│   ├── metadata.py          # JSON/CSV de metadata reproducible
│   └── pipeline.py          # Orquesta los 6 pasos end-to-end
│
├── tests/
│   ├── test_auth.py
│   ├── test_palm_detector.py
│   └── test_catalog.py
│
├── .env                     # SH_CLIENT_ID + SH_CLIENT_SECRET (NUNCA subir)
├── .gitignore
├── requirements.txt
├── config.yaml              # Parámetros centralizados
└── main.py                  # Punto de entrada CLI
```

---

## 1. Instalación

### 1.1. Entorno virtual

```powershell
# Asegúrate de tener Python 3.11+ (proyecto probado con 3.13)
python -m venv .venv
.\.venv\Scripts\activate
```

### 1.2. Dependencias

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` contiene las versiones mínimas oficiales:

| Paquete         | Versión mínima | Propósito |
|-----------------|----------------|-----------|
| `sentinelhub`   | 3.11.x         | Sentinel Hub Catalog + Process API |
| `rasterio`      | 1.5.x          | Lectura / escritura GeoTIFF, máscara, polygonize |
| `geopandas`     | 1.1.x          | GeoDataFrames (límites, parcelas, AOIs) |
| `shapely`       | 2.1.x          | Geometrías válidas / operaciones topológicas |
| `pyproj`        | 3.7.x          | Proyecciones dinámicas UTM por centroide |
| `numpy`         | 2.0+           | Arrays n-d |
| `pandas`        | 3.0+           | DataFrames de reportes y estadísticas |
| `python-dotenv` | 1.0+           | Cargar credenciales de `.env` |
| `requests`      | 2.31+          | Cliente HTTP para OAuth y Catalog |
| `pyyaml`        | 6.0+           | Parsear `config.yaml` |
| `scipy`         | 1.14+          | `scipy.ndimage.label` componentes conexos palma |
| `tqdm`          | 4.65+          # Barras de progreso opcionales |

---

## 2. Configuración

### 2.1. Credenciales Copernicus (`.env`)

El proyecto usa **OAuth2 Client Credentials** contra `identity.dataspace.copernicus.eu`.
Crea un archivo `.env` en la raíz con tu OAuth Client ya creado:

```dotenv
SH_CLIENT_ID=tu_client_id
SH_CLIENT_SECRET=tu_client_secret
```

- **NUNCA** compartas este archivo ni lo subas a Git (`.gitignore` lo excluye).
- **NO imprimas** sus valores desde el código. El módulo `src/auth.py` lee y reutiliza el token automáticamente durante ~30 min.

### 2.2. Parámetros (`config.yaml`)

Todo valor configurable vive en `config.yaml`. No es necesario editar Python.

```yaml
test_mode: true                         # true => 1 parcela x 1 mes x 1 imagen. Solo cuando esté OK pasar a false.

study_area:
  name: Santander
  country: Colombia
  boundary_path: "data/boundaries/santander.geojson"

sentinel:
  collection: sentinel-2-l2a
  max_cloud_cover: 20                   # % máximo de nubes (catálogo)
  resolution: 10                        # Resolución objetivo en metros
  bands:
    - B01
    - B02
    - B03
    - B04
    - B05
    - B06
    - B07
    - B08
    - B8A
    - B09
    - B11
    - B12

temporal:
  start_date: "2025-01-01"              # Rango configurable. Luego 2024, 2026, etc.
  end_date:   "2025-12-31"
  months: 12

palm:
  map_zip_path: "data/palm_map/GlobalOilPalm_OP-extent.zip"
  map_dir:     "data/palm_map/GlobalOilPalm_OP-extent"
  classes: [1, 2]                       # 1=industrial, 2=smallholder
  minimum_area_hectares: 0.5
  output_aoi: "data/aoi/palma_santander.geojson"

catalog:
  limit_per_page: 20
  max_pages: 50
  save_responses: true
  save_dir: "data/catalog"

output:
  root: "data/processed"
  crop_type: "palma"
  format: "GTiff"

logging:
  level: INFO
```

---

## 3. Fuente del mapa de palma

El dataset de referencia es:

> **Global oil palm extent and planting year from 1990 to 2021**  
> Distribuido como 609 teselas GeoTIFF de 100 × 100 km a 10 m de resolución.  
> CRS oficial: **EPSG:4326 (WGS84)**.
> Clases:
> - `0` = Otras coberturas
> - `1` = Palma **industrial**
> - `2` = Palma **pequeños productores**

El pipeline **no modifica** los TIFF originales ni el ZIP.
`palm_detector.py` funciona así:

1. Inspecciona automáticamente los 609 GeoTIFF (halla CRS, resolución, bounds).
2. Determina qué **teselas intersectan el límite de Santander** y descarta las demás.
3. Recorta (mask/crop) cada tesela candidata al polígono de Santander.
4. Se queda solo con valores 1 y 2.
5. Agrupa píxeles contiguos con `scipy.ndimage.label` (conectividad 8).
6. Polygoniza con `rasterio.features.shapes` en una sola pasada por tesela.
7. Reproyecta cada polígono al UTM dinámico según su centroide para calcular **área en hectáreas**.
8. Filtra las regiones < 0.5 ha.
9. Asigna IDs `PALMA_0001` … `PALMA_####` ordenados descendente por área (la finca más grande es PALMA_0001).
10. Guarda `data/aoi/palma_santander.geojson` en EPSG:4326.

Resultado obtenido para Santander (validación de este repositorio):

| Clase      | Nº polígonos | Área total (ha) | Parcela máx (ha) |
|------------|--------------|-----------------|------------------|
| Industrial | 200          | 41,963          | 2,953 (PALMA_0001) |
| Smallholder| 2,234        | 25,905          | 207 |
| **Total**  | **2,434**    | **67,868**      | - |

---

## 4. Sentinel-2 Level-2A y bandas

El pipeline trabaja exclusivamente con el producto **Sentinel-2 L2A** (*Bottom-of-Atmosphere / Surface Reflectance*) de Copernicus.

### Bandas utilizadas (12 oficiales)

| Banda | Longitud central | Resolución nativa | Descripción |
|-------|------------------|-------------------|-------------|
| **B01** | 443 nm | 60 m | Coastal / aerosol |
| **B02** | 490 nm | 10 m | Azul |
| **B03** | 560 nm | 10 m | Verde |
| **B04** | 665 nm | 10 m | Rojo |
| **B05** | 705 nm | 20 m | Red Edge 1 |
| **B06** | 740 nm | 20 m | Red Edge 2 |
| **B07** | 783 nm | 20 m | Red Edge 3 |
| **B08** | 842 nm | 10 m | NIR |
| **B8A** | 865 nm | 20 m | NIR ancho |
| **B09** | 945 nm | 60 m | Vapor de agua |
| **B11** | 1610 nm | 20 m | SWIR 1 |
| **B12** | 2190 nm | 20 m | SWIR 2 |

### ¿Por qué NO se incluye B10?

- **B10** (1375 nm, Cirrus) **solo forma parte de Sentinel-2 L1C**.
- En L2A, B10 **no es una banda de reflectancia de superficie** (se usa durante el procesamiento atmosférico, pero no está presente en el producto final).
- Metodológicamente, **NO inventamos una banda B10** falsa. En la tesis se justifica la diferencia: 12 bandas L2A oficiales frente a 13 bandas L1C.

### Resolución objetivo

Todas las bandas (nativas 10/20/60 m) se remuestrean a **10 m** para el array final, garantizando que tengan las mismas dimensiones espaciales. El remuestreo se hace en `preprocessing.py` con `rasterio.warp.reproject` (bilinear para reflectancia; nearest-neighbor cuando se introduzcan máscaras de clasificación).

---

## 5. Sentinel Hub Catalog API (descubrimiento)

Endpoint oficial:

```
POST https://sh.dataspace.copernicus.eu/catalog/v1/search
```

Se autentica con token OAuth (`identity.dataspace.copernicus.eu`) y se envía un request STAC estándar:

- `collections: ["sentinel-2-l2a"]`
- `datetime: "<start>Z/<end>Z"`  (con hora y zona `Z` para evitar HTTP 400)
- `bbox` o `intersects` con el AOI de la parcela
- `filter: cql2-json` con `eo:cloud_cover <= max_cloud_cover`
- `limit` + paginación (sigue el link `rel=next`)

Las respuestas se guardan opcionalmente en `data/catalog/search_*_p*_timestamp.json` para depuración / reproducibilidad.

---

## 6. Selección mensual de imágenes

Para cada parcela (ej. `PALMA_0001`) y cada mes del periodo:

1. Se consultan escenas de L2A con `eo:cloud_cover <= 20 %`.
2. Se ordenan ascendentemente por cobertura nubosa y, en caso de empate, por fecha.
3. Se escoge la mejor escena disponible.
4. Si el mes **no tiene ninguna imagen válida**:
   - **NO se inventan datos**
   - **NO se duplica la imagen de otro mes**
   - Se registra `status = "unavailable"` en la selección y en la metadata final

Esto evita introducir ruido en el dataset y documenta fielmente la disponibilidad de datos.

---

## 7. Sentinel Hub Process API (descarga)

Endpoint oficial:

```
POST https://sh.dataspace.copernicus.eu/process/v1
```

El pipeline usa la librería `sentinelhub` (`SentinelHubRequest`) con:

- **Colección**: `DataCollection.SENTINEL2_L2A`
- **Evalscript V3**: un solo `DEFAULT` que empaqueta
  - 12 bandas de reflectancia (`B01 … B12`), y
  - La banda SCL (*Scene Classification Layer*) como última banda.
- **AOI / bbox**: únicamente el polígono de la parcela (no la escena entera).
- **Resolución**: calculada a partir de `bbox_to_dimensions(resolution=10)`.
- **Mosaicking**: `mosaickingOrder="leastCC"` (para minimizar nubes residuales).
- **Ventana temporal**: +/- 5 días alrededor de la fecha de la escena seleccionada para permitir mosaicos óptimos.

Salida para cada parcela/mes:

```
data/processed/palma/PALMA_0001/
├── 2025-01.tif             # GeoTIFF multibanda con 12 bandas reflectancia a 10 m
├── 2025-01_cloud_mask.tif  # uint8 (1=válido, 0=inválido/nube, 255=nodata)
├── 2025-01_metadata.json   # metadata por muestra
└── selections.json         # reporte mensual completo
```

---

## 8. Máscara de nubes con SCL

L2A incluye la **Scene Classification Layer (SCL)** con 12 clases de ESA:

| Valor | Clase                         | Categoría en máscara |
|-------|-------------------------------|----------------------|
| 0     | NO_DATA                       | NODATA (255)         |
| 1     | SATURATED_OR_DEFECTIVE        | INVÁLIDO (0)         |
| 2     | DARK_AREA_PIXELS              | válido (1)           |
| 3     | CLOUD_SHADOWS                 | INVÁLIDO (0)         |
| 4     | VEGETATION                    | válido (1)           |
| 5     | NOT_VEGETATED                 | válido (1)           |
| 6     | WATER                         | válido (1)           |
| 7     | UNCLASSIFIED                  | INVÁLIDO (0)         |
| 8     | CLOUD_MEDIUM_PROBABILITY      | INVÁLIDO (0)         |
| 9     | CLOUD_HIGH_PROBABILITY        | INVÁLIDO (0)         |
| 10    | THIN_CIRRUS                   | INVÁLIDO (0)         |
| 11    | SNOW / ICE                    | válido (1)           |

Se calcula además el **cloud cover REAL del AOI** (no el de la escena) y se guarda en la metadata como `local_cloud_cover_pct`.

---

## 9. Metadata por muestra

Cada `2025-01_metadata.json` contiene:

```json
{
  "crop_id": "PALMA_0001",
  "crop_type": "oil_palm",
  "class_name": "Industrial",
  "class_value": 1,
  "area_ha": 2953.41,
  "date": "2025-01-15",
  "year": 2025,
  "month": 1,
  "scene_cloud_cover": 8.4,
  "local_cloud_cover_pct": 2.1,
  "resolution": 10,
  "crs": "EPSG:4326",
  "bbox": [-74.01, 7.10, -73.89, 7.25],
  "source_collection": "sentinel-2-l2a",
  "sentinel_product_id": "S2A_MSIL2A_..._SEN2COR_...",
  "bands": ["B01","B02","B03","B04","B05","B06","B07","B08","B8A","B09","B11","B12"],
  "image_path": "data/processed/palma/PALMA_0001/2025-01.tif",
  "image_width": 1321,
  "image_height": 1675,
  "image_dtype": "float32",
  "cloud_mask_path": "data/processed/palma/PALMA_0001/2025-01_cloud_mask.tif",
  "status": "available",
  "error": null
}
```

Y al finalizar el proceso completo, se genera `data/processed/palma/dataset_summary.csv` con **todas** las muestras en formato tabular (ideal para análisis de la tesis).

---

## 10. Modo de ejecución

### 10.1. Modo PRUEBA (por defecto)

En `config.yaml`, `test_mode: true`. El pipeline:

1. Detecta palma y lee `palma_santander.geojson`.
2. Selecciona solo **1 parcela** (la de mayor área, `PALMA_0001`).
3. Para esa parcela consulta solo **1 mes**.
4. Si hay imagen disponible, descarga solo **1 imagen**.
5. Genera 1 `metadata.json`, 1 `cloud_mask.tif`.

Esto permite validar toda la cadena **sin gastar cuota ni tiempo** en un dataset completo.

```powershell
python main.py
```

### 10.2. Modo COMPLETO

Antes de cambiarlo, asegúrate de que el test funcionó. Edita `config.yaml`:

```yaml
test_mode: false
```

Vuelve a lanzar:

```powershell
python main.py
```

Antes de empezar descargas, el programa **imprime un resumen** y pide **confirmación explícita `s/N`**:

```
==============================================================
  PIPELINE TFG - PALMA DE ACEITE SANTANDER x SENTINEL-2 L2A
==============================================================
  Modo de ejecución : PRODUCCIÓN (TODAS LAS PARCELAS)
  Zona de estudio    : Santander, Colombia
  Parcelas detectadas: 2434
  Área total         : 67,868.12 ha
  Periodo temporal   : 2025-01-01 a 2025-12-31
  Cantidad de meses  : 12
  Colección Sentinel : sentinel-2-l2a
  Resolución objetivo: 10 m
  Bandas (12) : B01,B02,B03,B04,B05,B06,B07,B08,B8A,B09,B11,B12
  Máx. cloud cover   : 20%
==============================================================
MODO PRODUCCIÓN: Se intentarán procesar 2434 parcelas x 12 meses.
¿Continuar con la descarga masiva? [s/N]:
```

Si contestas cualquier cosa distinta a `s/si/y/yes`, el pipeline aborta y no descarga nada.

---

## 11. Pruebas unitarias

Tres suites básicas (no requieren internet salvo test_auth si quieres token real):

```powershell
python tests\test_auth.py
python tests\test_palm_detector.py
python tests\test_catalog.py
```

- **test_auth.py**: valida carga del config, credenciales no vacías, 12 bandas (sin B10), construcción del SHConfig.
- **test_palm_detector.py**: lee `santander.geojson`, confirma ~609 TIFF, encuentra ~7 teselas que intersectan Santander, valida CRS EPSG:4326; si existe `palma_santander.geojson` lee y muestra resumen.
- **test_catalog.py**: construcción de intervalos ISO STAC, selección mensual (febrero bisiesto), `_pick_best` ordena por cloud_cover ASC, máscara SCL conocida, preprocess de GeoTIFF pequeño.

---

## 12. Arquitectura de logging

Mensajes de progreso estructurados en 6 pasos:

```
2025-03-18 10:12:01 - src.pipeline - INFO - [1/6] Detectando palma en Santander ...
2025-03-18 10:12:05 - src.pipeline - INFO - [2/6] Preparando AOI ...
2025-03-18 10:12:05 - src.pipeline - INFO - [3+4/6] Consultando Catalog API y seleccionando ...
2025-03-18 10:12:10 - src.pipeline - INFO -   [5/6] Descargando bandas via Process API...
2025-03-18 10:12:14 - src.pipeline - INFO -   [6/6] Preprocessing (res=10m, CRS WGS84, 12 bandas)
```

---

## 13. Errores manejados

El pipeline no oculta excepciones silenciosamente. Se tratan explícitamente:

- `HTTPError` / `MaxRetryError` de Catalog o Process API
- Token de OAuth expirado → se renueva automáticamente
- AOI con geometría inválida → `aoi_generator.repair_geometries` intenta buffer 0 / make_valid
- Sin imágenes en un mes → status `unavailable` (no error)
- GeoTIFF corrupto al leer → status `error` con mensaje
- CRS incompatible → reproyección dinámica
- Timeout de request → log y pasa a la siguiente parcela/mes

---

## 14. Reproducibilidad

- **Ninguna fecha aleatoria**. El rango temporal viene de `temporal.start_date` / `temporal.end_date`.
- Todos los parámetros quedan en `config.yaml` + `metadata.json`.
- Las respuestas del Catalog se pueden guardar en `data/catalog/`.
- El ZIP y TIFF originales del mapa de palma **nunca se modifican**.
- Archivos existentes no se borran sin previa confirmación.

---

## 15. Extensibilidad a cacao y café

Aunque el dataset de referencia actual es de palma, el diseño es extensible:

1. Crear `data/cacao_map/` o `data/cafe_map/` con sus datasets de referencia.
2. Duplicar la sección `palm:` de `config.yaml` por `cacao:` / `cafe:`.
3. Parámetros a actualizar:
   - `output.crop_type` (nombre subcarpeta)
   - clases relevantes y área mínima
   - si existe dataset vectorial en vez de raster, escribir un módulo paralelo a `palm_detector.py` (ej. `crop_polygonizer.py`) que lea y prepare AOIs con `crop_id` en `data/aoi/`.
4. El resto de la cadena (AOI → Catalog → selector → Process API → cloud mask → preproc → metadata) es **independiente del cultivo**.

---

## 16. Checklist de validación final (antes de procesar todo)

- [ ] `.env` existe y contiene `SH_CLIENT_ID` / `SH_CLIENT_SECRET` reales.
- [ ] `python tests\test_auth.py` pasa.
- [ ] `python tests\test_palm_detector.py` pasa.
- [ ] `python tests\test_catalog.py` pasa.
- [ ] `data/boundaries/santander.geojson` existe y es válido en QGIS.
- [ ] `data/palm_map/GlobalOilPalm_OP-extent/` contiene los 609 TIFF.
- [ ] `config.yaml` → `test_mode: true`.
- [ ] Lanzas `python main.py`. Se descarga **solo 1 imagen**.
- [ ] Inspeccionas `data/processed/palma/PALMA_0001/2025-01.tif` en QGIS:
  - 12 bandas B01,B02,B03,B04,B05,B06,B07,B08,B8A,B09,B11,B12.
  - Resolución ≈ 10 m (o equivalente en grados: ~0.00009°).
  - CRS EPSG:4326.
  - Dimensiones coherentes.
- [ ] `cloud_mask.tif` muestra zonas de nubes correctamente.
- [ ] `metadata.json` tiene todos los campos.
- [ ] **Solo entonces** cambias `test_mode: false` y ejecutas a escala.

---

## 17. Referencias oficiales

- Sentinel Hub (CDSE): https://documentation.dataspace.copernicus.eu/APIs/SentinelHub.html
- Catalog (STAC): https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Catalog.html
- Process API: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process.html
- Evalscript V3: https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Evalscript/V3.html
- Sentinel-2 L2A / SCL: https://sentinels.copernicus.eu/web/sentinel/technical-guides/sentinel-2-msi/level-2a/algorithm
- Global Oil Palm Extent dataset:
  - Referencia científica: *Descals et al. (2022). Global oil palm extent and planting year from 1990 to 2021.*

---

### Nota metodológica

> Este repositorio utiliza el dataset *Global Oil Palm Extent* como **fuente de candidatos y etiquetas espaciales de referencia**, sin afirmar que representa la verdad absoluta de la distribución actual de palma en Santander. El estudiante debe, en la tesis, contrastar y documentar explícitamente esta diferencia frente a la realidad de campo.
