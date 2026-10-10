import { useEffect, useState } from "react";
import { Calendar, History, Sprout, Target } from "lucide-react";
import type { Navegar } from "../App";
import { api, type FechaHistorial } from "../api";
import { Aviso, Cabecera, Cargando, fechaLarga, ha, InsigniaEstado, Miniatura, nombreClase, num } from "../ui";

type Filtro = "" | "anomalia" | "cargadas";
const FILTROS: { id: Filtro; texto: string }[] = [
  { id: "", texto: "Todos" }, { id: "anomalia", texto: "Con regiones anómalas" }, { id: "cargadas", texto: "Cargados por usuarios" },
];
const LOTE = 20;

export default function Historial({ navegar }: { navegar: Navegar }) {
  const [filtro, setFiltro] = useState<Filtro>("");
  const [escenas, setEscenas] = useState<FechaHistorial[] | null>(null);
  const [total, setTotal] = useState(0);
  const [cargandoMas, setCargandoMas] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEscenas(null);
    api.historial(LOTE, 0, filtro || undefined)
      .then((r) => { setEscenas(r.escenas); setTotal(r.total); })
      .catch((e) => setError(e.message));
  }, [filtro]);

  const mas = () => {
    setCargandoMas(true);
    api.historial(LOTE, escenas!.length, filtro || undefined)
      .then((r) => setEscenas([...escenas!, ...r.escenas]))
      .catch((e) => setError(e.message))
      .finally(() => setCargandoMas(false));
  };

  return (
    <>
      <Cabecera titulo="Historial" subtitulo="Análisis por fecha, del más reciente al más antiguo" />
      <div className="px-4 sm:px-6 lg:px-0 py-6">
        <div className="flex gap-2 overflow-x-auto pb-1 mb-5 -mx-4 px-4 sm:mx-0 sm:px-0" role="tablist">
          {FILTROS.map((f) => (
            <button key={f.id} role="tab" aria-selected={filtro === f.id} onClick={() => setFiltro(f.id)}
                    className={`shrink-0 px-4 py-2 rounded-full text-sm border transition-colors
                      ${filtro === f.id ? "bg-agro text-white border-agro dark:text-[#0f1f0f]" : "border-borde hover:bg-suave"}`}>
              {f.texto}
            </button>
          ))}
        </div>

        {error && <Aviso tipo="error">{error}</Aviso>}
        {!escenas && !error && <Cargando texto="Cargando historial…" />}
        {escenas && !escenas.length && (
          <div className="tarjeta p-10 text-center text-tenue">
            <History className="w-10 h-10 mx-auto mb-3 text-agro" />No hay análisis con este filtro.
          </div>
        )}
        {escenas && escenas.length > 0 && (
          <p className="text-sm text-tenue mb-3">{escenas.length} de {total} análisis</p>
        )}
        <div className="grid gap-3 md:grid-cols-2">
          {escenas?.map((e) => (
            <button key={e.id} onClick={() => navegar({ vista: "plantacion", plantacion: e.crop_id, escena: e.id })}
                    className="tarjeta flex gap-4 p-3 sm:p-4 text-left shadow-sm hover:shadow-md transition-shadow aparecer">
              <Miniatura escenaId={e.id} alt={`${e.crop_id} el ${e.fecha}`} className="w-20 h-20 sm:w-24 sm:h-24 shrink-0 rounded-lg" />
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2 mb-1.5">
                  <h4 className="truncate">{e.crop_id}</h4>
                  <InsigniaEstado estado={e.estado} corto />
                </div>
                <div className="flex items-center gap-1.5 text-sm text-tenue mb-1">
                  <Sprout className="w-4 h-4 shrink-0" /><span className="truncate">{nombreClase(e.clase)}</span>
                  {e.origen === "cargada" && <span className="text-xs text-[#7c3aed] dark:text-[#c4b5fd]">· cargada</span>}
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                  <span className="flex items-center gap-1.5 text-tenue"><Calendar className="w-4 h-4" />{fechaLarga(e.fecha)}</span>
                  <span className="flex items-center gap-1.5 text-tenue"><Target className="w-4 h-4" />{ha(e.ha_consenso)}</span>
                  <span className="px-2 py-0.5 bg-suave rounded text-xs">NDVI {num(e.ndvi_mediana)}</span>
                </div>
              </div>
            </button>
          ))}
        </div>
        {escenas && escenas.length < total && (
          <button className="boton-borde w-full mt-4" onClick={mas} disabled={cargandoMas}>
            {cargandoMas ? "Cargando…" : `Cargar más (${total - escenas.length} restantes)`}
          </button>
        )}
      </div>
    </>
  );
}
