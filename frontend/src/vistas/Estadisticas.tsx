import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis,
  YAxis } from "recharts";
import { AlertTriangle, BarChart3, Leaf, Sprout, Target } from "lucide-react";
import type { Navegar, Tema } from "../App";
import { api, type EstadoEscena, type Estadisticas as Datos } from "../api";
import { Aviso, Cabecera, Cargando, ESTADOS, estiloTooltip, ha, Kpi, mesCorto, nombreClase, num, useColores } from "../ui";

export default function Estadisticas({ tema, navegar }: { tema: Tema; navegar: Navegar }) {
  const c = useColores(tema);
  const [d, setD] = useState<Datos | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.estadisticas().then(setD).catch((e) => setError(e.message));
  }, []);

  const ejes = { tick: { fontSize: 11, fill: c.tenue }, stroke: c.borde };
  const colorEstado: Record<EstadoEscena, string> = { sin_anomalias: c.verde, puntual: c.amarillo, revisar: c.rojo };
  const torta = d ? (Object.keys(ESTADOS) as EstadoEscena[]).map((k) => ({ k, nombre: ESTADOS[k].corto, valor: d.estados[k] })) : [];
  const mensual = d?.mensual.map((m) => ({ ...m, etiqueta: mesCorto(`${m.mes}-01`) })) ?? [];

  return (
    <>
      <Cabecera titulo="Estadísticas" subtitulo="Indicadores del catálogo y tendencias por mes" />
      <div className="px-4 sm:px-6 lg:px-0 py-6 space-y-6">
        {error && <Aviso tipo="error">{error}</Aviso>}
        {!d && !error && <Cargando texto="Calculando indicadores…" />}
        {d && (
          <>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
              <Kpi icono={Leaf} titulo="NDVI mediano" valor={num(d.ndvi_mediana_ultima)} detalle="última fecha de cada plantación" />
              <Kpi icono={BarChart3} titulo="Análisis" valor={d.n_analisis} color="azul"
                   detalle={`${d.n_cargadas} cargados por usuarios`} />
              <Kpi icono={AlertTriangle} titulo="A revisar" valor={d.estados.revisar} color="amarillo"
                   detalle={`de ${d.n_plantaciones} plantaciones`} />
              <Kpi icono={Target} titulo="Área anómala" valor={ha(d.ha_consenso_ultima)} color="rojo"
                   detalle={`${num(100 * d.ha_consenso_ultima / Math.max(1e-9, d.ha_evaluable_ultima))} % de la palma evaluable`} />
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <section className="tarjeta p-4 lg:col-span-2">
                <h3 className="mb-1">Evolución del NDVI por tipo de productor</h3>
                <p className="text-xs text-tenue mb-4">Mediana mensual del NDVI de la palma evaluable.</p>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={mensual} margin={{ left: -12, right: 8, top: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={c.borde} />
                    <XAxis dataKey="etiqueta" {...ejes} />
                    <YAxis domain={["auto", "auto"]} {...ejes} width={48} tickFormatter={(v: number) => v.toFixed(2)} />
                    <Tooltip {...estiloTooltip(c)} formatter={(v: number) => num(v, 3)} />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line type="monotone" dataKey="ndvi_industrial" name="Industrial" stroke={c.verde} strokeWidth={2.5}
                          dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                    <Line type="monotone" dataKey="ndvi_pequeno" name="Pequeño productor" stroke={c.tierra} strokeWidth={2.5}
                          dot={{ r: 3 }} connectNulls isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              </section>

              <section className="tarjeta p-4">
                <h3 className="mb-1">Estado de las plantaciones</h3>
                <p className="text-xs text-tenue mb-2">Según su fecha más reciente. “Revisar”: consenso ≥ {num(d.umbral_revisar_pct, 1)} %
                  de la palma evaluable.</p>
                <div className="flex flex-col sm:flex-row items-center gap-4">
                  <div className="w-44 h-44 shrink-0">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={torta} dataKey="valor" nameKey="nombre" innerRadius={45} outerRadius={75} paddingAngle={2}
                             isAnimationActive={false} stroke={c.tarjeta}>
                          {torta.map((t) => <Cell key={t.k} fill={colorEstado[t.k]} />)}
                        </Pie>
                        <Tooltip {...estiloTooltip(c)} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <ul className="flex-1 w-full space-y-2">
                    {torta.map((t) => (
                      <li key={t.k} className="flex items-center justify-between text-sm p-2 rounded-lg bg-suave/50">
                        <span className="flex items-center gap-2">
                          <span className="w-3 h-3 rounded-full" style={{ background: colorEstado[t.k] }} />{ESTADOS[t.k].texto}
                        </span>
                        <strong>{t.valor}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              </section>

              <section className="tarjeta p-4">
                <h3 className="mb-1">Análisis por mes</h3>
                <p className="text-xs text-tenue mb-2">Fechas procesadas (catálogo y cargadas).</p>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={mensual} margin={{ left: -20, right: 8, top: 4 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={c.borde} vertical={false} />
                    <XAxis dataKey="etiqueta" {...ejes} />
                    <YAxis allowDecimals={false} {...ejes} />
                    <Tooltip {...estiloTooltip(c)} cursor={{ fill: c.suave, opacity: 0.5 }}
                             formatter={(v: number) => [v, "Análisis"]} />
                    <Bar dataKey="n_analisis" fill={c.verde} radius={[8, 8, 0, 0]} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
              </section>

              <section className="tarjeta p-4 lg:col-span-2">
                <h3 className="mb-3">Resumen por tipo de productor</h3>
                <div className="grid gap-3 sm:grid-cols-2">
                  {d.por_clase.map((k) => (
                    <div key={k.clase} className="flex items-center justify-between gap-3 p-4 bg-suave/60 rounded-lg">
                      <div className="flex items-center gap-3 min-w-0">
                        <Sprout className={`w-6 h-6 shrink-0 ${k.clase === "industrial" ? "text-agro" : "text-tierra"}`} />
                        <div className="min-w-0">
                          <div className="font-semibold">{nombreClase(k.clase)}</div>
                          <div className="text-sm text-tenue">{k.n_plantaciones} plantaciones · NDVI {num(k.ndvi_mediana)}</div>
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className={k.n_revisar ? "text-rojo font-semibold" : "text-agro font-semibold"}>
                          {k.n_revisar ? `${k.n_revisar} a revisar` : "Sin alertas"}
                        </div>
                        <div className="text-xs text-tenue">{ha(k.ha_consenso)} anómalas</div>
                      </div>
                    </div>
                  ))}
                </div>
                <button className="mt-4 text-sm font-medium text-agro hover:underline" onClick={() => navegar({ vista: "inicio" })}>
                  Ver plantaciones ordenadas por prioridad →
                </button>
              </section>
            </div>
          </>
        )}
      </div>
    </>
  );
}
