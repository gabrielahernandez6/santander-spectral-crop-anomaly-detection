// Cliente de la API REST del backend y tipos de sus respuestas.
import type { FeatureCollection, Geometry } from "geojson";

export type Limites = [[number, number], [number, number]];

/** Semáforo de una fecha (lo calcula el backend; ver estado_escena en app/main.py). */
export type EstadoEscena = "sin_anomalias" | "puntual" | "revisar";

export interface Usuario {
  id: number;
  nombre: string;
  correo: string;
  municipio: string | null;
  creado: number;
}

export interface Estado {
  modelos_cargados: boolean;
  error_modelos: string | null;
  n_ubicaciones: number;
  modelos: {
    demo: boolean;
    detectores: string[];
    consenso_min: number;
    versiones: Record<string, string>;
    entrenamiento: { n_ubicaciones?: number; demo?: boolean; fecha?: string };
    avisos: string[];
  } | null;
}

export interface UltimaFecha {
  id: string;
  fecha: string;
  ha_consenso: number;
  pct_consenso: number;
  n_regiones: number;
  ndvi_mediana: number | null;
  estado: EstadoEscena;
}

export interface Ubicacion {
  crop_id: string;
  clase: string;
  area_ha: number | null;
  split: string | null;
  limites: Limites;
  centro: [number, number];
  n_fechas: number;
  n_cargadas: number;
  ha_palma_ref: number;
  ha_consenso_max: number | null;
  ultima: UltimaFecha | null;
}

export interface Fecha {
  id: string;
  crop_id: string;
  fecha: string;
  origen: "catalogo" | "cargada";
  nube: number | null;
  pct_valido: number;
  pct_evaluable: number;
  ha_evaluable: number;
  ha_consenso: number;
  pct_consenso: number;
  n_regiones: number;
  ndvi_mediana: number | null;
  estado: EstadoEscena;
}

export interface FechaHistorial extends Fecha {
  clase: string;
}

export interface Estadisticas {
  n_plantaciones: number;
  n_analisis: number;
  n_cargadas: number;
  ha_palma: number;
  ha_evaluable_ultima: number;
  ha_consenso_ultima: number;
  ndvi_mediana_ultima: number | null;
  estados: Record<EstadoEscena, number>;
  mensual: { mes: string; n_analisis: number; ha_consenso: number; ndvi_industrial: number | null;
    ndvi_pequeno: number | null }[];
  por_clase: { clase: string; n_plantaciones: number; ndvi_mediana: number | null; n_revisar: number;
    ha_consenso: number }[];
  umbral_revisar_pct: number;
}

export interface Capa {
  id: string;
  nombre: string;
  grupo: "base" | "indice" | "mascara" | "anomalia" | "detector";
  leyenda: string;
}

export interface Resumen {
  escena_id: string;
  crop_id: string;
  fecha: string;
  origen: string;
  nube: number | null;
  limites: Limites;
  px_ha: number;
  pct_valido: number;
  ha_evaluable: number;
  pct_por_detector: Record<string, number>;
  pct_consenso: number;
  ha_consenso: number;
  n_regiones: number;
  ndvi_mediana?: number | null;
  consenso_min: number;
  demo: boolean;
  capas: Capa[];
}

export interface PropiedadesRegion {
  region: number;
  px: number;
  ha: number;
  lat: number;
  lon: number;
  votos_medios: number;
  persistencia_media: number | null;
  z_NDVI: number;
  z_GNDVI: number;
  z_NDRE: number;
  z_NDMI: number;
  caida_principal: string;
  indice_caida: string | null;
  firma: Record<string, number>;
  firma_normal: Record<string, number>;
  crop_id: string;
  fecha: string;
}

export type Regiones = FeatureCollection<Geometry, PropiedadesRegion>;

export interface Pixel {
  lat: number;
  lon: number;
  valido: boolean;
  evaluable: boolean;
  reflectancia: Record<string, number>;
  indices: Record<string, number>;
  detectores: { detector: string; puntaje: number | null; umbral: number; anomalo: boolean }[];
  votos: number | null;
  consenso: boolean;
  persistencia: number | null;
  region: number | null;
}

export interface Trabajo {
  id: string;
  estado: "en_cola" | "en_proceso" | "terminado" | "error";
  progreso: number;
  mensaje: string;
  escena_id: string | null;
}

/** Error de la API con su código HTTP (401 = sesión vencida o inexistente). */
export class ErrorApi extends Error {
  constructor(message: string, public estado: number) {
    super(message);
  }
}

// La app avisa aquí cuando una respuesta 401 indica que la sesión terminó.
let alExpirarSesion: () => void = () => {};
export const fijarAlExpirarSesion = (f: () => void) => { alExpirarSesion = f; };

async function pedir<T>(url: string, init?: RequestInit, avisar401 = true): Promise<T> {
  const r = await fetch(url, { credentials: "same-origin", ...init });
  if (!r.ok) {
    let detalle = `${r.status} ${r.statusText}`;
    try {
      const cuerpo = await r.json();
      if (cuerpo?.detail) detalle = typeof cuerpo.detail === "string" ? cuerpo.detail : JSON.stringify(cuerpo.detail);
    } catch {
      /* respuesta sin JSON */
    }
    if (r.status === 401 && avisar401) alExpirarSesion();
    throw new ErrorApi(detalle, r.status);
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

const json = (cuerpo: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo),
});
const e = encodeURIComponent;

export const api = {
  yo: () => pedir<Usuario>("/api/auth/yo", undefined, false),
  ingresar: (correo: string, contrasena: string) =>
    pedir<Usuario>("/api/auth/ingreso", json({ correo, contrasena }), false),
  registrar: (datos: { nombre: string; correo: string; contrasena: string; municipio?: string }) =>
    pedir<Usuario>("/api/auth/registro", json(datos), false),
  salir: () => pedir<void>("/api/auth/salida", { method: "POST" }, false),

  estado: () => pedir<Estado>("/api/estado"),
  ubicaciones: () => pedir<Ubicacion[]>("/api/ubicaciones"),
  fechas: (cropId: string) => pedir<Fecha[]>(`/api/ubicaciones/${e(cropId)}/fechas`),
  historial: (limite: number, desde: number, solo?: "anomalia" | "cargadas") =>
    pedir<{ total: number; escenas: FechaHistorial[] }>(
      `/api/escenas?limite=${limite}&desde=${desde}${solo ? `&solo=${solo}` : ""}`),
  estadisticas: () => pedir<Estadisticas>("/api/estadisticas"),
  resumen: (escenaId: string) => pedir<Resumen>(`/api/escenas/${e(escenaId)}/resumen`),
  regiones: (escenaId: string) => pedir<Regiones>(`/api/escenas/${e(escenaId)}/regiones`),
  pixel: (escenaId: string, lat: number, lon: number) =>
    pedir<Pixel>(`/api/escenas/${e(escenaId)}/pixel?lat=${lat}&lon=${lon}`),
  trabajo: (id: string) => pedir<Trabajo>(`/api/trabajos/${e(id)}`),
  cargarEscena: (cropId: string, archivo: File, fecha?: string) => {
    const datos = new FormData();
    datos.append("crop_id", cropId);
    datos.append("archivo", archivo);
    if (fecha) datos.append("fecha", fecha);
    return pedir<{ trabajo_id: string }>("/api/escenas", { method: "POST", body: datos });
  },
  urlCapa: (escenaId: string, capa: string) => `/api/escenas/${e(escenaId)}/capas/${e(capa)}`,
  urlRegionesGeojson: (escenaId: string) => `/api/escenas/${e(escenaId)}/regiones?descargar=true`,
  urlRegionesCsv: (escenaId: string) => `/api/escenas/${e(escenaId)}/regiones.csv`,
  urlResumenCsv: (cropId: string) => `/api/ubicaciones/${e(cropId)}/resumen.csv`,
};
