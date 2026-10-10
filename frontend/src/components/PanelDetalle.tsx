import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip,
  XAxis, YAxis } from "recharts";
import { Crosshair, MapPin, Search, X } from "lucide-react";
import type { Pixel, PropiedadesRegion, Resumen } from "../api";
import { type Colores, estiloTooltip, num } from "../ui";

const BANDAS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"];
const INDICES = ["NDVI", "GNDVI", "NDRE", "NDMI"] as const;

/** Qué revisar en campo según el índice que más cae (orientación, no diagnóstico). */
export const QUE_MIRAR: Record<string, string> = {
  NDMI: "Agua del dosel: revise riego, drenaje o señales de estrés hídrico.",
  NDRE: "Borde rojo: posible estrés temprano (clorofila), antes de que caiga el NDVI.",
  GNDVI: "Clorofila: revise nutrición o sanidad foliar.",
  NDVI: "Vigor: pérdida de follaje o de biomasa.",
};

const ejes = (c: Colores) => ({ tick: { fontSize: 11, fill: c.tenue }, stroke: c.borde });

export function GraficoDetectores({ resumen, detectores, c }: { resumen: Resumen; detectores: string[]; c: Colores }) {
  const datos = detectores.map((d) => ({ d, v: resumen.pct_por_detector[d] ?? 0 }));
  return (
    <>
      <ResponsiveContainer width="100%" height={210}>
        <BarChart layout="vertical" margin={{ left: 0, right: 16, top: 4, bottom: 0 }} data={datos}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke={c.borde} />
          <XAxis type="number" {...ejes(c)} unit=" %" />
          <YAxis type="category" dataKey="d" width={110} {...ejes(c)} />
          <Tooltip {...estiloTooltip(c)} cursor={{ fill: c.suave, opacity: 0.5 }}
                   formatter={(v: number) => [`${v.toFixed(2)} %`, "Palma evaluable marcada"]} />
          <ReferenceLine x={3} stroke={c.tenue} strokeDasharray="4 3" />
          <Bar isAnimationActive={false} dataKey="v" fill={c.naranja} radius={[0, 6, 6, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-tenue">Línea punteada: 3 %, lo que cada detector marca en palma normal por calibración.</p>
    </>
  );
}

export function DetalleRegion({ r, c, onCerrar }: { r: PropiedadesRegion; c: Colores; onCerrar: () => void }) {
  const firma = BANDAS.map((b) => ({ banda: b, region: r.firma[b], normal: r.firma_normal[b] }));
  const z = INDICES.map((i) => ({ i, z: r[`z_${i}`] }));
  return (
    <section className="tarjeta p-4 aparecer" aria-label={`Región ${r.region}`}>
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-amarillo/15 text-amarillo"><Search className="w-5 h-5" /></div>
          <div>
            <h4>Región {r.region}</h4>
            <p className="text-xs text-tenue">{r.lat.toFixed(6)}, {r.lon.toFixed(6)}</p>
          </div>
        </div>
        <BotonCerrar onClick={onCerrar} />
      </div>
      <dl className="grid grid-cols-2 gap-2 mb-4">
        <Celda t="Área" v={`${num(r.ha, 3)} ha`} d={`${r.px} píxeles`} />
        <Celda t="Votos medios" v={`${num(r.votos_medios)} de 6`} />
        <Celda t="Persistencia" v={r.persistencia_media === null ? "—" : `${Math.round(100 * r.persistencia_media)} %`}
               d="de las fechas" />
        <Celda t="Mayor caída" v={r.caida_principal} />
      </dl>
      {r.indice_caida && (
        <div className="p-3 mb-4 rounded-lg bg-agro/10 border border-agro/20 text-sm flex gap-2">
          <span className="w-2 h-2 rounded-full bg-amarillo mt-1.5 shrink-0" />
          <span><strong>Qué revisar en campo.</strong> {QUE_MIRAR[r.indice_caida]}</span>
        </div>
      )}
      <h5 className="text-sm font-semibold mb-2">Firma espectral frente a la palma normal</h5>
      <ResponsiveContainer width="100%" height={190}>
        <LineChart data={firma} margin={{ left: -8, right: 8, top: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={c.borde} />
          <XAxis dataKey="banda" {...ejes(c)} />
          <YAxis {...ejes(c)} width={48} />
          <Tooltip {...estiloTooltip(c)} formatter={(v: number) => v.toFixed(4)} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line isAnimationActive={false} dataKey="normal" name="Palma normal" stroke={c.verde} dot={false} strokeWidth={2} />
          <Line isAnimationActive={false} dataKey="region" name="Región" stroke={c.rojo} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
      <h5 className="text-sm font-semibold mt-4 mb-2">Índices respecto a la palma normal (σ)</h5>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={z} margin={{ left: -8, right: 8, top: 4 }}>
          <XAxis dataKey="i" {...ejes(c)} />
          <YAxis {...ejes(c)} width={40} />
          <Tooltip {...estiloTooltip(c)} cursor={{ fill: c.suave, opacity: 0.5 }}
                   formatter={(v: number) => [`${v.toFixed(2)} σ`, "Desviación"]} />
          <ReferenceLine y={-1} stroke={c.tenue} strokeDasharray="4 3" />
          <ReferenceLine y={0} stroke={c.tenue} />
          <Bar isAnimationActive={false} dataKey="z" radius={[4, 4, 4, 4]}>
            {z.map((d) => <Cell key={d.i} fill={d.z <= -1 ? c.rojo : c.azul} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </section>
  );
}

export function DetallePixel({ p, onCerrar }: { p: Pixel; onCerrar: () => void }) {
  return (
    <section className="tarjeta p-4 aparecer" aria-label="Píxel consultado">
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <div className="p-2 rounded-lg bg-azul/10 text-azul"><Crosshair className="w-5 h-5" /></div>
          <div>
            <h4>Píxel consultado</h4>
            <p className="text-xs text-tenue flex items-center gap-1"><MapPin className="w-3 h-3" />
              {p.lat.toFixed(5)}, {p.lon.toFixed(5)}</p>
          </div>
        </div>
        <BotonCerrar onClick={onCerrar} />
      </div>
      {!p.valido && <p className="text-sm text-tenue mb-3">Nube o sin dato en esta fecha.</p>}
      {p.valido && !p.evaluable && (
        <p className="text-sm text-tenue mb-3">No es palma evaluable (fuera de la palma de referencia, sin dosel
          persistente o cerca de una nube): los detectores no lo analizan.</p>
      )}
      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-2 mb-3">
        {Object.entries(p.indices).map(([k, v]) => <Celda key={k} t={k} v={v.toFixed(3)} />)}
        <Celda t="Persistencia" v={p.persistencia === null ? "—" : `${Math.round(100 * p.persistencia)} %`} />
      </dl>
      {p.evaluable && (
        <div className="overflow-x-auto -mx-1">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-tenue text-xs">
                <th className="px-1 py-2 font-medium">Detector</th><th className="px-1 py-2 font-medium text-right">Puntaje</th>
                <th className="px-1 py-2 font-medium text-right">Umbral</th><th className="px-1 py-2" />
              </tr>
            </thead>
            <tbody>
              {p.detectores.map((d) => (
                <tr key={d.detector} className="border-t border-borde">
                  <td className="px-1 py-2">{d.detector}</td>
                  <td className="px-1 py-2 text-right tabular-nums">{num(d.puntaje, 3)}</td>
                  <td className="px-1 py-2 text-right tabular-nums text-tenue">{num(d.umbral, 3)}</td>
                  <td className="px-1 py-2 text-right">
                    <span className={`text-xs px-2 py-0.5 rounded-full ${d.anomalo ? "bg-rojo/10 text-rojo" : "bg-agro/10 text-agro"}`}>
                      {d.anomalo ? "anómalo" : "normal"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className={`mt-3 text-sm font-medium ${p.consenso ? "text-rojo" : "text-agro"}`}>
            {p.votos} de 6 votos · {p.consenso ? "anomalía de consenso" : "sin consenso"}
          </p>
        </div>
      )}
    </section>
  );
}

function Celda({ t, v, d }: { t: string; v: string; d?: string }) {
  return (
    <div className="bg-suave/60 rounded-lg px-3 py-2">
      <dt className="text-xs text-tenue">{t}</dt>
      <dd className="font-semibold tabular-nums">{v}</dd>
      {d && <dd className="text-xs text-tenue">{d}</dd>}
    </div>
  );
}

function BotonCerrar({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} aria-label="Cerrar" className="p-1.5 rounded-lg text-tenue hover:bg-suave hover:text-texto">
      <X className="w-5 h-5" />
    </button>
  );
}
