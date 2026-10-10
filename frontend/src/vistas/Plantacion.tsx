import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bar, CartesianGrid, Cell, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, CloudSun, Download, Layers, Leaf, MousePointerClick, Plus, Ruler, Share2, Target, X } from "lucide-react";
import type { Navegar, Tema } from "../App";
import { api, type Estado, type Fecha, type Pixel, type PropiedadesRegion, type Regiones, type Resumen,
  type Ubicacion } from "../api";
import { Aviso, Cabecera, Cargando, ESTADOS, estiloTooltip, fechaLarga, ha, mesCorto, nombreClase, num,
  useColores } from "../ui";
import Mapa from "../components/Mapa";
import PanelCapas, { CAPAS_INICIALES, type EstadoCapas } from "../components/PanelCapas";
import { DetallePixel, DetalleRegion, GraficoDetectores } from "../components/PanelDetalle";

interface Props {
  cropId: string;
  escenaInicial?: string;
  estado: Estado | null;
  tema: Tema;
  navegar: Navegar;
  reemplazar: Navegar;
}

export default function Plantacion({ cropId, escenaInicial, estado, tema, navegar, reemplazar }: Props) {
  const c = useColores(tema);
  const [ubicacion, setUbicacion] = useState<Ubicacion | null>(null);
  const [fechas, setFechas] = useState<Fecha[] | null>(null);
  const [resumen, setResumen] = useState<Resumen | null>(null);
  const [regiones, setRegiones] = useState<Regiones | null>(null);
  const [region, setRegion] = useState<PropiedadesRegion | null>(null);
  const [pixel, setPixel] = useState<Pixel | null>(null);
  const [capas, setCapas] = useState<EstadoCapas>(CAPAS_INICIALES);
  const [verCapas, setVerCapas] = useState(false);
  const [cargando, setCargando] = useState(false);
  const [consultando, setConsultando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const detalle = useRef<HTMLDivElement>(null);

  const fallo = (e: unknown) => setError(e instanceof Error ? e.message : String(e));

  useEffect(() => {
    setFechas(null); setUbicacion(null); setResumen(null); setRegiones(null); setError(null);
    api.ubicaciones().then((us) => {
      const u = us.find((x) => x.crop_id === cropId);
      if (!u) setError(`La plantación ${cropId} no existe en el catálogo.`);
      setUbicacion(u ?? null);
    }).catch(fallo);
    api.fechas(cropId).then(setFechas).catch(fallo);
  }, [cropId]);

  // Fecha activa: la de la URL o, por defecto, la más reciente.
  const escenaId = useMemo(() => {
    if (!fechas?.length) return null;
    return fechas.some((f) => f.id === escenaInicial) ? escenaInicial! : fechas[fechas.length - 1].id;
  }, [fechas, escenaInicial]);
  const fecha = fechas?.find((f) => f.id === escenaId) ?? null;

  useEffect(() => {
    if (!escenaId) return;
    let vigente = true;
    setCargando(true); setRegion(null); setPixel(null);
    Promise.all([api.resumen(escenaId), api.regiones(escenaId)])
      .then(([r, g]) => { if (vigente) { setResumen(r); setRegiones(g); } })
      .catch(fallo)
      .finally(() => vigente && setCargando(false));
    return () => { vigente = false; };
  }, [escenaId]);

  const elegirFecha = (id: string) => reemplazar({ vista: "plantacion", plantacion: cropId, escena: id });

  const mostrarDetalle = () => {
    // En celular el detalle queda debajo del mapa: se desplaza hasta él.
    if (window.matchMedia("(max-width: 1023px)").matches) {
      setTimeout(() => detalle.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    }
  };

  const consultarPixel = useCallback((lat: number, lon: number) => {
    if (!escenaId) return;
    setConsultando(true);
    api.pixel(escenaId, lat, lon).then((p) => {
      setPixel(p);
      const r = p.region ? regiones?.features.find((f) => f.properties.region === p.region) : undefined;
      setRegion(r ? r.properties : null);
      mostrarDetalle();
    }).catch(fallo).finally(() => setConsultando(false));
  }, [escenaId, regiones]);

  const compartir = async () => {
    const url = window.location.href;
    try {
      if (navigator.share) {
        await navigator.share({ title: `AgroSpec · ${cropId}`, url });
      } else {
        await navigator.clipboard.writeText(url);
        setAviso("Enlace copiado al portapapeles");
      }
    } catch { /* el usuario canceló */ }
  };
  useEffect(() => {
    if (!aviso) return;
    const t = setTimeout(() => setAviso(null), 2500);
    return () => clearTimeout(t);
  }, [aviso]);

  const serie = (fechas ?? []).map((f) => ({ ...f, etiqueta: mesCorto(f.fecha) + (f.origen === "cargada" ? "*" : "") }));
  const demo = estado?.modelos?.demo || resumen?.demo;

  return (
    <>
      <Cabecera titulo={cropId} volver={() => navegar({ vista: "inicio" })}
                subtitulo={ubicacion ? `${nombreClase(ubicacion.clase)} · ${ha(ubicacion.ha_palma_ref)} de palma de referencia`
                                     : "Cargando…"}
                accion={
                  <button onClick={compartir} aria-label="Compartir" title="Compartir enlace"
                          className="p-2 hover:bg-white/10 rounded-lg transition-colors"><Share2 className="w-6 h-6" /></button>
                }>
        {/* Fechas disponibles */}
        {fechas && fechas.length > 0 && (
          <div className="mt-5 -mx-4 sm:-mx-6 px-4 sm:px-6 flex gap-2 overflow-x-auto pb-1 [scrollbar-width:thin]"
               role="tablist" aria-label="Fechas">
            {fechas.map((f) => (
              <button key={f.id} role="tab" aria-selected={f.id === escenaId} onClick={() => elegirFecha(f.id)}
                      className={`shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors
                        ${f.id === escenaId ? "bg-white text-[#1a5c1a] font-semibold" : "bg-white/10 hover:bg-white/20"}`}>
                <span className="w-2 h-2 rounded-full" style={{ background: ESTADOS[f.estado].color }} />
                {fechaLarga(f.fecha)}{f.origen === "cargada" && " *"}
              </button>
            ))}
          </div>
        )}
      </Cabecera>

      <div className="px-4 sm:px-6 lg:px-0 py-6 space-y-4">
        {error && <Aviso tipo="error" titulo="Algo falló">{error}</Aviso>}
        {demo && (
          <Aviso tipo="demo">
            Resultados con modelos <strong>DEMO</strong> (entrenamiento reducido): sirven para probar la app, no para
            la tesis.
          </Aviso>
        )}
        {fechas && !fechas.length && <Aviso tipo="alerta">Esta plantación no tiene fechas procesadas.</Aviso>}

        <div className="grid grid-cols-1 gap-4 lg:gap-6 lg:grid-cols-[minmax(0,1fr)_380px] xl:grid-cols-[minmax(0,1fr)_420px] items-start">
          {/* Mapa */}
          <div className="lg:sticky lg:top-6 space-y-2">
            <div className="tarjeta overflow-hidden relative h-[55vh] min-h-80 lg:h-[calc(100dvh-120px)] lg:max-h-[760px] shadow-lg">
              <Mapa ubicacion={ubicacion} resumen={resumen} escenaId={escenaId} capas={capas} regiones={regiones}
                    regionSeleccionada={region?.region ?? null} pixel={pixel}
                    onRegion={(r) => { setRegion(r); setPixel(null); mostrarDetalle(); }} onPixel={consultarPixel} />
              {fecha && (
                <div className="absolute top-3 left-14 z-[500] flex flex-wrap gap-2 pointer-events-none">
                  <span className="bg-tarjeta/90 backdrop-blur-sm px-3 py-1.5 rounded-lg text-sm font-medium shadow">
                    {fechaLarga(fecha.fecha)}
                  </span>
                </div>
              )}
              {resumen && (
                <button onClick={() => setVerCapas(!verCapas)} aria-expanded={verCapas}
                        className="absolute top-3 right-3 z-[600] flex items-center gap-2 bg-tarjeta/95 backdrop-blur-sm px-3 py-2
                                   rounded-lg text-sm font-medium shadow hover:bg-tarjeta">
                  {verCapas ? <X className="w-4 h-4" /> : <Layers className="w-4 h-4" />} Capas
                </button>
              )}
              {verCapas && resumen && (
                <div className="absolute z-[550] top-14 right-3 left-3 sm:left-auto sm:w-80 max-h-[calc(100%-4.5rem)] overflow-y-auto
                                bg-tarjeta/97 backdrop-blur rounded-xl shadow-xl border border-borde p-4 aparecer">
                  <PanelCapas resumen={resumen} estado={capas} onCambio={setCapas} />
                </div>
              )}
              {(cargando || consultando) && (
                <div className="absolute inset-x-0 bottom-3 z-[500] flex justify-center pointer-events-none">
                  <span className="bg-tarjeta/95 px-4 py-2 rounded-full text-sm shadow flex items-center gap-2">
                    <span className="w-4 h-4 border-2 border-agro border-t-transparent rounded-full animate-spin" />
                    {consultando ? "Consultando el píxel…" : "Cargando la escena…"}
                  </span>
                </div>
              )}
            </div>
            <p className="text-xs text-tenue flex items-center gap-1.5 px-1">
              <MousePointerClick className="w-4 h-4 shrink-0" />
              Toque una región amarilla para ver su firma espectral, o cualquier punto para ver los valores del píxel.
            </p>
          </div>

          {/* Panel lateral */}
          <div className="space-y-4 min-w-0">
            <div ref={detalle} className="space-y-4 scroll-mt-4">
              {region && <DetalleRegion r={region} c={c} onCerrar={() => setRegion(null)} />}
              {pixel && <DetallePixel p={pixel} onCerrar={() => setPixel(null)} />}
            </div>

            {!fechas && !error && <Cargando />}
            {fecha && (
              <>
                <EstadoFecha f={fecha} />
                <div className="grid grid-cols-2 gap-3">
                  <Metrica icono={Leaf} titulo="NDVI mediano" valor={num(fecha.ndvi_mediana)} detalle="palma evaluable" />
                  <Metrica icono={Ruler} titulo="Palma evaluable" valor={ha(fecha.ha_evaluable)}
                           detalle={`${num(fecha.pct_evaluable, 1)} % del recuadro`} />
                  <Metrica icono={Target} titulo="Anomalía consenso" valor={ha(fecha.ha_consenso)}
                           detalle={`${num(fecha.pct_consenso)} % · ${fecha.n_regiones} regiones`} tono="rojo" />
                  <Metrica icono={CloudSun} titulo="Nubes" valor={fecha.nube === null ? "—" : `${num(fecha.nube, 1)} %`}
                           detalle={`${num(fecha.pct_valido, 1)} % píxeles válidos`} tono="azul" />
                </div>
              </>
            )}

            {serie.length > 0 && (
              <section className="tarjeta p-4">
                <div className="flex items-center gap-2 mb-1"><Activity className="w-5 h-5 text-agro" /><h4>Evolución</h4></div>
                <p className="text-xs text-tenue mb-3">NDVI mediano (línea) y hectáreas de consenso (barras). Toque una
                  barra para cambiar de fecha.</p>
                <ResponsiveContainer width="100%" height={220}>
                  <ComposedChart data={serie} margin={{ left: -12, right: 0, top: 6 }}>
                    <defs>
                      <linearGradient id="gradNdvi" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={c.verde} stopOpacity={0.3} />
                        <stop offset="95%" stopColor={c.verde} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={c.borde} vertical={false} />
                    <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: c.tenue }} stroke={c.borde} />
                    <YAxis yAxisId="ha" tick={{ fontSize: 11, fill: c.tenue }} stroke={c.borde} width={44} />
                    <YAxis yAxisId="ndvi" orientation="right" domain={[0, 1]} tick={{ fontSize: 11, fill: c.tenue }}
                           stroke={c.borde} width={34} />
                    <Tooltip {...estiloTooltip(c)} cursor={{ fill: c.suave, opacity: 0.5 }}
                             labelFormatter={(_, p) => {
                               const f = p?.[0]?.payload as Fecha | undefined;
                               return f ? `${fechaLarga(f.fecha)} · ${ESTADOS[f.estado].corto}` : "";
                             }}
                             formatter={(v: number, n: string) => n === "NDVI" ? [num(v), n] : [`${num(v)} ha`, n]} />
                    <Bar yAxisId="ha" dataKey="ha_consenso" name="Consenso" radius={[6, 6, 0, 0]} isAnimationActive={false}
                         cursor="pointer" onClick={(d) => elegirFecha((d as unknown as Fecha).id)}>
                      {serie.map((f) => (
                        <Cell key={f.id} fill={f.id === escenaId ? c.rojo : c.rojo + "66"} />
                      ))}
                    </Bar>
                    <Line yAxisId="ndvi" dataKey="ndvi_mediana" name="NDVI" stroke={c.verde} strokeWidth={2.5}
                          dot={{ r: 3, fill: c.verde }} isAnimationActive={false} connectNulls />
                  </ComposedChart>
                </ResponsiveContainer>
              </section>
            )}

            {resumen && (
              <section className="tarjeta p-4">
                <h4 className="mb-1">Detectores</h4>
                <p className="text-xs text-tenue mb-3">% de la palma evaluable que marca cada detector. El consenso exige
                  {` ${resumen.consenso_min}`} votos de 6.</p>
                <GraficoDetectores resumen={resumen} detectores={estado?.modelos?.detectores ?? Object.keys(resumen.pct_por_detector)} c={c} />
              </section>
            )}

            {escenaId && (
              <section className="tarjeta p-4">
                <h4 className="mb-3">Exportar y compartir</h4>
                <div className="grid grid-cols-2 gap-2">
                  <a className="boton text-sm px-3" href={api.urlRegionesGeojson(escenaId)}>
                    <Download className="w-4 h-4" /> GeoJSON
                  </a>
                  <a className="boton-borde text-sm px-3" href={api.urlRegionesCsv(escenaId)}>
                    <Download className="w-4 h-4" /> Regiones CSV
                  </a>
                  <a className="boton-borde text-sm px-3" href={api.urlResumenCsv(cropId)}>
                    <Download className="w-4 h-4" /> Resumen CSV
                  </a>
                  <button className="boton-borde text-sm px-3" onClick={compartir}>
                    <Share2 className="w-4 h-4" /> Compartir
                  </button>
                </div>
                <button className="boton-borde w-full mt-2 text-sm" disabled={!estado?.modelos_cargados}
                        onClick={() => navegar({ vista: "nuevo", plantacion: cropId })}>
                  <Plus className="w-4 h-4" /> Analizar una fecha nueva
                </button>
              </section>
            )}
          </div>
        </div>
      </div>

      {aviso && (
        <div role="status" className="fixed bottom-24 lg:bottom-8 left-1/2 -translate-x-1/2 z-[2000] bg-texto text-fondo
                                      px-4 py-2 rounded-full text-sm shadow-lg aparecer">
          {aviso}
        </div>
      )}
    </>
  );
}

function EstadoFecha({ f }: { f: Fecha }) {
  const e = ESTADOS[f.estado];
  const Icono = e.icono;
  const textos = {
    sin_anomalias: "El consenso de detectores no encontró regiones anómalas del tamaño mínimo en esta fecha.",
    puntual: `${f.n_regiones} regiones con anomalía de consenso (${num(f.pct_consenso)} % de la palma evaluable), por debajo del umbral de revisión.`,
    revisar: `${f.n_regiones} regiones con anomalía de consenso (${num(f.pct_consenso)} % de la palma evaluable). Priorice la visita de campo.`,
  };
  return (
    <div className={`flex items-start gap-3 p-4 rounded-xl border ${e.clase} border-current/20`}>
      <Icono className="w-6 h-6 shrink-0" />
      <div className="flex-1">
        <div className="flex flex-wrap items-center gap-2 mb-1">
          <h4>{e.texto}</h4>
          {f.origen === "cargada" && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-[#7c3aed]/10 text-[#7c3aed] dark:text-[#c4b5fd]">Fecha cargada</span>
          )}
        </div>
        <p className="text-sm text-tenue">{textos[f.estado]} No es un diagnóstico: verifique en campo.</p>
      </div>
    </div>
  );
}

function Metrica({ icono: Icono, titulo, valor, detalle, tono = "agro" }:
  { icono: typeof Leaf; titulo: string; valor: string; detalle?: string; tono?: "agro" | "rojo" | "azul" }) {
  const t = { agro: "text-agro", rojo: "text-rojo", azul: "text-azul" }[tono];
  return (
    <div className="tarjeta p-3 sm:p-4 min-w-0">
      <div className="flex items-center gap-2 mb-1.5">
        <Icono className={`w-4 h-4 sm:w-5 sm:h-5 shrink-0 ${t}`} />
        <span className="text-xs sm:text-sm text-tenue truncate">{titulo}</span>
      </div>
      <div className="text-lg sm:text-xl font-semibold tabular-nums">{valor}</div>
      {detalle && <div className="text-xs text-tenue mt-0.5">{detalle}</div>}
    </div>
  );
}
