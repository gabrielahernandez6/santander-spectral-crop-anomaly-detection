import type { Capa, Resumen } from "../api";

export interface EstadoCapas {
  visibles: Record<string, boolean>;
  opacidad: Record<string, number>;
  detector: string; // id de la capa del detector que se muestra ("" = ninguno)
  contornos: boolean; // contornos de las regiones anómalas
}

export const CAPAS_INICIALES: EstadoCapas = {
  visibles: { rgb: true, consenso: true },
  opacidad: { rgb: 1, consenso: 0.85 },
  detector: "",
  contornos: true,
};

const GRUPOS: { grupo: Capa["grupo"]; titulo: string }[] = [
  { grupo: "base", titulo: "Imagen" },
  { grupo: "indice", titulo: "Índices espectrales" },
  { grupo: "mascara", titulo: "Máscaras (módulo 2)" },
  { grupo: "anomalia", titulo: "Anomalías (módulo 3)" },
];

/** Capas en orden de dibujo (de abajo hacia arriba) con su visibilidad y opacidad. */
export function ORDEN_CAPAS(capas: Capa[], e: EstadoCapas) {
  const orden: Capa["grupo"][] = ["base", "indice", "mascara", "detector", "anomalia"];
  return [...capas]
    .sort((a, b) => orden.indexOf(a.grupo) - orden.indexOf(b.grupo))
    .map((c) => ({
      ...c,
      visible: c.grupo === "detector" ? e.detector === c.id : !!e.visibles[c.id],
      opacidad: e.opacidad[c.id] ?? 0.85,
    }));
}

interface Props {
  resumen: Resumen;
  estado: EstadoCapas;
  onCambio: (e: EstadoCapas) => void;
}

export default function PanelCapas({ resumen, estado, onCambio }: Props) {
  const fijar = (id: string, cambios: { visible?: boolean; opacidad?: number }) =>
    onCambio({
      ...estado,
      visibles: cambios.visible === undefined ? estado.visibles : { ...estado.visibles, [id]: cambios.visible },
      opacidad: cambios.opacidad === undefined ? estado.opacidad : { ...estado.opacidad, [id]: cambios.opacidad },
    });
  const detectores = resumen.capas.filter((c) => c.grupo === "detector");

  return (
    <div className="space-y-4 text-sm">
      {GRUPOS.map(({ grupo, titulo }) => (
        <fieldset key={grupo}>
          <legend className="text-xs font-semibold uppercase tracking-wide text-tenue mb-2">{titulo}</legend>
          <div className="space-y-2">
            {resumen.capas.filter((c) => c.grupo === grupo).map((c) => (
              <div key={c.id} title={c.leyenda}>
                <label className="flex items-center gap-2.5 py-0.5">
                  <input type="checkbox" className="w-4 h-4 accent-[var(--agro-green)]" checked={!!estado.visibles[c.id]}
                         onChange={(e) => fijar(c.id, { visible: e.target.checked })} />
                  {c.nombre}
                </label>
                {estado.visibles[c.id] && (
                  <div className="pl-6.5 mt-1 space-y-1">
                    <input type="range" min={0} max={1} step={0.05} value={estado.opacidad[c.id] ?? 0.85}
                           className="w-full accent-[var(--agro-green)]" aria-label={`Opacidad de ${c.nombre}`}
                           onChange={(e) => fijar(c.id, { opacidad: Number(e.target.value) })} />
                    <p className="text-xs text-tenue">{c.leyenda}</p>
                    <Escala id={c.id} />
                  </div>
                )}
              </div>
            ))}
            {grupo === "anomalia" && (
              <label className="flex items-center gap-2.5 py-0.5">
                <input type="checkbox" className="w-4 h-4 accent-[var(--agro-green)]" checked={estado.contornos}
                       onChange={(e) => onCambio({ ...estado, contornos: e.target.checked })} />
                Contorno de las regiones
              </label>
            )}
          </div>
        </fieldset>
      ))}
      <fieldset>
        <legend className="text-xs font-semibold uppercase tracking-wide text-tenue mb-2">Detector individual</legend>
        <select className="campo py-2" value={estado.detector} aria-label="Detector que se muestra"
                onChange={(e) => onCambio({ ...estado, detector: e.target.value })}>
          <option value="">Ninguno</option>
          {detectores.map((d) => (
            <option key={d.id} value={d.id}>{d.nombre} ({resumen.pct_por_detector[d.nombre]?.toFixed(2)} %)</option>
          ))}
        </select>
        {estado.detector && (
          <input type="range" min={0} max={1} step={0.05} value={estado.opacidad[estado.detector] ?? 0.85}
                 className="w-full mt-2 accent-[var(--agro-green)]" aria-label="Opacidad del detector"
                 onChange={(e) => fijar(estado.detector, { opacidad: Number(e.target.value) })} />
        )}
      </fieldset>
    </div>
  );
}

const ESCALAS: Record<string, { fondo: string; min: string; max: string }> = {
  indice: { fondo: "linear-gradient(90deg,#a50026,#f46d43,#fee08b,#d9ef8b,#66bd63,#006837)", min: "−0,2", max: "1" },
  votos: { fondo: "linear-gradient(90deg,#000004,#4f127b,#b5367a,#fb8761,#fcfdbf)", min: "1", max: "6" },
  persistencia: { fondo: "linear-gradient(90deg,#000004,#550f6d,#ba3655,#f98e09,#fcffa4)", min: "0", max: "1" },
};

function Escala({ id }: { id: string }) {
  const e = ESCALAS[["NDVI", "GNDVI", "NDRE", "NDMI"].includes(id) ? "indice" : id];
  if (!e) return null;
  return (
    <div className="flex items-center gap-2 text-xs text-tenue">
      <span>{e.min}</span><div className="flex-1 h-2 rounded" style={{ background: e.fondo }} /><span>{e.max}</span>
    </div>
  );
}
