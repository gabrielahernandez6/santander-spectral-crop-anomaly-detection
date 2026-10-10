// Piezas de interfaz compartidas por las vistas (estilo AgroSpec del diseño en Figma).
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, CircleAlert, type LucideIcon } from "lucide-react";
import { api, type EstadoEscena } from "./api";

// ------------------------------------------------------------------
// Formato
// ------------------------------------------------------------------
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

/** "2025-04-14" → "14 abr 2025" (sin pasar por Date, para no correr la fecha por zona horaria). */
export function fechaLarga(iso: string): string {
  const [a, m, d] = iso.split("-");
  return `${Number(d)} ${MESES[Number(m) - 1]} ${a}`;
}

export function mesCorto(iso: string): string {
  const [a, m] = iso.split("-");
  return `${MESES[Number(m) - 1]} ${a.slice(2)}`;
}

export const num = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : v.toLocaleString("es-CO", { minimumFractionDigits: d, maximumFractionDigits: d });

/** Hectáreas con la precisión que tiene sentido según el tamaño. */
export const ha = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${num(v, v >= 100 ? 0 : v >= 10 ? 1 : 2)} ha`;

export const nombreClase = (c: string) =>
  c === "industrial" ? "Industrial" : c === "smallholder" ? "Pequeño productor" : c;

export const iniciales = (nombre: string) =>
  nombre.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("");

// ------------------------------------------------------------------
// Semáforo
// ------------------------------------------------------------------
export const ESTADOS: Record<EstadoEscena, { texto: string; corto: string; icono: LucideIcon; clase: string;
  color: string }> = {
  sin_anomalias: { texto: "Sin anomalías relevantes", corto: "Sin anomalías", icono: CheckCircle2,
    clase: "text-agro bg-agro/10", color: "var(--agro-green)" },
  puntual: { texto: "Anomalías puntuales", corto: "Puntual", icono: AlertTriangle,
    clase: "text-amarillo bg-amarillo/15", color: "var(--agro-yellow)" },
  revisar: { texto: "Revisar en campo", corto: "Revisar", icono: CircleAlert,
    clase: "text-rojo bg-rojo/10", color: "var(--agro-red)" },
};

export function InsigniaEstado({ estado, corto = false, solida = false }:
  { estado: EstadoEscena | null | undefined; corto?: boolean; solida?: boolean }) {
  if (!estado) return <span className="px-2.5 py-1 rounded-full text-xs bg-suave text-tenue">Sin datos</span>;
  const e = ESTADOS[estado];
  const Icono = e.icono;
  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap
                      ${solida ? "bg-tarjeta/95 shadow-sm backdrop-blur-sm " + e.clase.split(" ")[0] : e.clase}`}>
      <Icono className="w-3.5 h-3.5" aria-hidden />
      {corto ? e.corto : e.texto}
    </span>
  );
}

// ------------------------------------------------------------------
// Bloques
// ------------------------------------------------------------------
/** Cabecera verde degradada de cada vista (en escritorio, con bordes redondeados). */
export function Cabecera({ titulo, subtitulo, volver, accion, children }:
  { titulo: string; subtitulo?: ReactNode; volver?: () => void; accion?: ReactNode; children?: ReactNode }) {
  return (
    <header className="cabecera px-4 sm:px-6 pt-6 sm:pt-8 pb-6 lg:rounded-2xl lg:mt-6 lg:shadow-sm">
      <div className="flex items-start gap-3">
        {volver && (
          <button onClick={volver} aria-label="Volver" className="p-2 -ml-2 hover:bg-white/10 rounded-lg transition-colors">
            <ArrowLeft className="w-6 h-6" />
          </button>
        )}
        <div className="flex-1 min-w-0">
          <h1 className="text-white truncate">{titulo}</h1>
          {subtitulo && <p className="text-white/80 mt-1">{subtitulo}</p>}
        </div>
        {accion}
      </div>
      {children}
    </header>
  );
}

export function Kpi({ icono: Icono, titulo, valor, detalle, color = "agro" }:
  { icono: LucideIcon; titulo: string; valor: ReactNode; detalle?: ReactNode;
    color?: "agro" | "azul" | "amarillo" | "rojo" }) {
  const tonos = { agro: "text-agro bg-agro/10", azul: "text-azul bg-azul/10", amarillo: "text-amarillo bg-amarillo/15",
    rojo: "text-rojo bg-rojo/10" };
  return (
    <div className="tarjeta p-4">
      <div className={`inline-flex p-2 rounded-lg mb-3 ${tonos[color]}`}><Icono className="w-5 h-5" /></div>
      <div className="text-sm text-tenue">{titulo}</div>
      <div className={`text-2xl font-semibold mt-0.5 ${tonos[color].split(" ")[0]}`}>{valor}</div>
      {detalle && <div className="text-xs text-tenue mt-1">{detalle}</div>}
    </div>
  );
}

/** Imagen real de la escena (color verdadero) con la anomalía de consenso encima. */
export function Miniatura({ escenaId, alt, className = "" }: { escenaId: string | null | undefined; alt: string;
  className?: string }) {
  const [fallo, setFallo] = useState(false);
  useEffect(() => setFallo(false), [escenaId]);
  if (!escenaId || fallo) {
    return <div className={`bg-gradient-to-br from-agro/30 to-azul/20 ${className}`} aria-hidden />;
  }
  return (
    <div className={`relative overflow-hidden bg-suave ${className}`}>
      <img src={api.urlCapa(escenaId, "rgb")} alt={alt} loading="lazy" onError={() => setFallo(true)}
           className="absolute inset-0 w-full h-full object-cover pixelada" />
      <img src={api.urlCapa(escenaId, "consenso")} alt="" loading="lazy" aria-hidden
           className="absolute inset-0 w-full h-full object-cover pixelada" />
    </div>
  );
}

export function Aviso({ tipo = "info", titulo, children }:
  { tipo?: "info" | "alerta" | "error" | "demo"; titulo?: string; children: ReactNode }) {
  const estilos = {
    info: "bg-agro/10 border-agro/20",
    alerta: "bg-amarillo/10 border-amarillo/30",
    error: "bg-rojo/10 border-rojo/30 text-rojo",
    demo: "bg-[#7c3aed]/10 border-[#7c3aed]/30",
  };
  return (
    <div role={tipo === "error" ? "alert" : "note"} className={`p-4 rounded-xl border ${estilos[tipo]}`}>
      {titulo && <h4 className="mb-1">{titulo}</h4>}
      <div className="text-sm text-tenue [&_strong]:text-texto">{children}</div>
    </div>
  );
}

export function Cargando({ texto = "Cargando…" }: { texto?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-tenue" role="status">
      <span className="w-5 h-5 border-2 border-agro border-t-transparent rounded-full animate-spin" />
      {texto}
    </div>
  );
}

/** Colores para Recharts: los SVG necesitan valores, no var(--x); se releen al cambiar de tema. */
export function useColores(tema: "claro" | "oscuro") {
  const [c, setC] = useState(() => leerColores());
  useEffect(() => setC(leerColores()), [tema]);
  return c;
}

function leerColores() {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    verde: v("--agro-green"), amarillo: v("--agro-yellow"), rojo: v("--agro-red"), azul: v("--agro-blue"),
    naranja: v("--agro-orange"), tierra: v("--agro-earth"), texto: v("--foreground"), tenue: v("--muted-foreground"),
    borde: v("--border"), tarjeta: v("--card"), suave: v("--muted"),
  };
}
export type Colores = ReturnType<typeof leerColores>;

export const estiloTooltip = (c: Colores) => ({
  contentStyle: { background: c.tarjeta, border: `1px solid ${c.borde}`, borderRadius: 10, fontSize: 12,
    color: c.texto, boxShadow: "0 4px 16px rgb(0 0 0 / 0.12)" },
  labelStyle: { color: c.texto, fontWeight: 600 },
  itemStyle: { color: c.texto },
});
