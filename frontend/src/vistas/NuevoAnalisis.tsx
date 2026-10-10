import { useEffect, useRef, useState, type DragEvent, type FormEvent } from "react";
import { BrainCircuit, CheckCircle2, FileArchive, Layers, Loader2, RotateCcw, Sigma, UploadCloud, XCircle,
  type LucideIcon } from "lucide-react";
import type { Navegar } from "../App";
import { api, type Estado, type Trabajo, type Ubicacion } from "../api";
import { Aviso, Cabecera, ha } from "../ui";

interface Props {
  estado: Estado | null;
  plantacionInicial?: string;
  navegar: Navegar;
}

// Pasos reales del procesamiento (servicio.procesar_escena_nueva) según el progreso que reporta el trabajo.
const PASOS: { hasta: number; texto: string; icono: LucideIcon }[] = [
  { hasta: 0.1, texto: "Leyendo las bandas Sentinel-2 y la máscara de nubes", icono: FileArchive },
  { hasta: 0.15, texto: "Calculando índices y palma evaluable", icono: Sigma },
  { hasta: 0.9, texto: "Ejecutando los seis detectores", icono: BrainCircuit },
  { hasta: 1.01, texto: "Consenso, regiones y capas del mapa", icono: Layers },
];

export default function NuevoAnalisis({ estado, plantacionInicial, navegar }: Props) {
  const [ubic, setUbic] = useState<Ubicacion[]>([]);
  const [cropId, setCropId] = useState(plantacionInicial ?? "");
  const [fecha, setFecha] = useState("");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [arrastrando, setArrastrando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trabajo, setTrabajo] = useState<Trabajo | null>(null);
  const [enviando, setEnviando] = useState(false);
  const temporizador = useRef<number>();

  useEffect(() => {
    api.ubicaciones().then(setUbic).catch((e) => setError(e.message));
    return () => window.clearInterval(temporizador.current);
  }, []);

  const volver = () => plantacionInicial ? navegar({ vista: "plantacion", plantacion: plantacionInicial })
                                         : navegar({ vista: "inicio" });
  const sinModelos = estado !== null && !estado.modelos_cargados;
  const u = ubic.find((x) => x.crop_id === cropId);

  const elegirArchivo = (f: File | undefined | null) => {
    setError(null);
    if (f && !f.name.toLowerCase().endsWith(".zip")) {
      setError("El archivo debe ser un .zip con la carpeta de la escena.");
      return;
    }
    setArchivo(f ?? null);
  };

  const soltar = (e: DragEvent) => {
    e.preventDefault();
    setArrastrando(false);
    elegirArchivo(e.dataTransfer.files?.[0]);
  };

  const enviar = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!archivo || !cropId) return;
    setError(null);
    setEnviando(true);
    try {
      const { trabajo_id } = await api.cargarEscena(cropId, archivo, fecha || undefined);
      setTrabajo({ id: trabajo_id, estado: "en_cola", progreso: 0, mensaje: "En cola", escena_id: null });
      temporizador.current = window.setInterval(async () => {
        try {
          const t = await api.trabajo(trabajo_id);
          setTrabajo(t);
          if (t.estado === "terminado" || t.estado === "error") window.clearInterval(temporizador.current);
        } catch (e) {
          window.clearInterval(temporizador.current);
          setError(e instanceof Error ? e.message : String(e));
        }
      }, 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(false);
    }
  };

  if (trabajo) {
    return <Procesando trabajo={trabajo} cropId={cropId} area={u?.ha_palma_ref} error={error}
                       onReintentar={() => { setTrabajo(null); setError(null); }}
                       onVer={(id) => navegar({ vista: "plantacion", plantacion: cropId, escena: id })} />;
  }

  return (
    <>
      <Cabecera titulo="Nuevo análisis" subtitulo="Procese una fecha nueva de una plantación del catálogo" volver={volver} />
      <div className="px-4 sm:px-6 lg:px-0 py-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px] items-start max-w-5xl">
          <form onSubmit={enviar} className="tarjeta p-5 sm:p-6 space-y-5">
            {sinModelos && (
              <Aviso tipo="error" titulo="Modelos no cargados">
                {estado?.error_modelos} Puede explorar resultados ya calculados, pero no analizar fechas nuevas.
              </Aviso>
            )}
            <label className="block">
              <span className="etiqueta">Plantación</span>
              <select className="campo appearance-none" required value={cropId} onChange={(e) => setCropId(e.target.value)}>
                <option value="">Seleccione la plantación</option>
                {ubic.map((x) => (
                  <option key={x.crop_id} value={x.crop_id}>
                    {x.crop_id} · {x.clase === "industrial" ? "industrial" : "pequeño productor"} · {ha(x.ha_palma_ref)}
                  </option>
                ))}
              </select>
              <span className="block text-xs text-tenue mt-1.5">Se usan la palma de referencia y el no-dosel ya
                calculados para esta plantación.</span>
            </label>

            <label className="block">
              <span className="etiqueta">Fecha de la escena (opcional)</span>
              <input type="date" className="campo" value={fecha} onChange={(e) => setFecha(e.target.value)} />
              <span className="block text-xs text-tenue mt-1.5">Solo si no viene en <code>metadata.json</code>.</span>
            </label>

            <div>
              <span className="etiqueta">Escena Sentinel-2 L2A (.zip)</span>
              <label onDragOver={(e) => { e.preventDefault(); setArrastrando(true); }}
                     onDragLeave={() => setArrastrando(false)} onDrop={soltar}
                     className={`block border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer
                       ${arrastrando ? "border-agro bg-agro/10" : archivo ? "border-agro/50 bg-agro/5" : "border-borde hover:bg-suave/50"}`}>
                <input type="file" accept=".zip,application/zip" className="sr-only"
                       onChange={(e) => elegirArchivo(e.target.files?.[0])} />
                {archivo ? (
                  <>
                    <FileArchive className="w-12 h-12 text-agro mx-auto mb-3" />
                    <p className="font-medium break-all">{archivo.name}</p>
                    <p className="text-sm text-tenue">{(archivo.size / 1048576).toFixed(1)} MB · toque para cambiarlo</p>
                  </>
                ) : (
                  <>
                    <UploadCloud className="w-12 h-12 text-tenue mx-auto mb-3" />
                    <p className="text-tenue mb-1"><span className="text-agro font-medium">Toque para elegir</span> o arrastre el archivo aquí</p>
                    <p className="text-xs text-tenue">Máximo 200 MB</p>
                  </>
                )}
              </label>
            </div>

            {error && <p role="alert" className="text-sm text-rojo bg-rojo/10 rounded-lg px-4 py-3">{error}</p>}

            <button type="submit" className="boton w-full" disabled={!archivo || !cropId || enviando || sinModelos}>
              {enviando ? <Loader2 className="w-5 h-5 animate-spin" /> : <BrainCircuit className="w-5 h-5" />}
              {enviando ? "Subiendo…" : "Procesar escena"}
            </button>
          </form>

          <aside className="space-y-4">
            <Aviso titulo="Formato del archivo">
              Comprima la carpeta de la escena, en el mismo formato del dataset: bandas{" "}
              <code>A_B02_(Raw).tiff</code> … <code>A_B12_(Raw).tiff</code>, <code>cloud_mask.tif</code> (1 = limpio) y,
              si la tiene, <code>metadata.json</code>.
            </Aviso>
            <Aviso tipo="alerta" titulo="Requisitos">
              La escena debe cubrir al menos el <strong>90 %</strong> del recuadro de la plantación y tener suficientes
              píxeles sin nubes. En CPU tarda desde segundos (pequeño productor) hasta varios minutos (industrial).
            </Aviso>
          </aside>
        </div>
      </div>
    </>
  );
}

function Procesando({ trabajo, cropId, area, error, onReintentar, onVer }:
  { trabajo: Trabajo; cropId: string; area?: number; error: string | null; onReintentar: () => void;
    onVer: (escenaId: string) => void }) {
  const pct = Math.round(100 * trabajo.progreso);
  const paso = PASOS.findIndex((p) => trabajo.progreso < p.hasta);
  const fallo = trabajo.estado === "error" || !!error;
  const listo = trabajo.estado === "terminado" && trabajo.escena_id;

  // Al terminar, abre el resultado tras un instante (para que se vea el 100 %).
  useEffect(() => {
    if (!listo) return;
    const t = setTimeout(() => onVer(trabajo.escena_id!), 1200);
    return () => clearTimeout(t);
  }, [listo, onVer, trabajo.escena_id]);

  return (
    <div className="fixed inset-0 z-[3000] flex flex-col items-center justify-center bg-gradient-to-b from-[#2d7a2d] to-[#1a5c1a] text-white overflow-y-auto py-10">
      <div className="absolute w-96 h-96 bg-white/10 rounded-full blur-3xl -top-48 -left-48 animate-pulse" aria-hidden />
      <div className="absolute w-96 h-96 bg-white/10 rounded-full blur-3xl -bottom-48 -right-48 animate-pulse" aria-hidden />
      <div className="relative z-10 flex flex-col items-center px-6 max-w-md w-full" role="status" aria-live="polite">
        <div className="mb-8 p-6 bg-white/10 rounded-full backdrop-blur-sm">
          {fallo ? <XCircle className="w-16 h-16" /> : listo ? <CheckCircle2 className="w-16 h-16" />
                 : <Loader2 className="w-16 h-16 animate-spin" />}
        </div>
        <h2 className="text-white mb-2 text-center">
          {fallo ? "No se pudo procesar" : listo ? "Análisis listo" : "Procesando análisis"}
        </h2>
        <p className="text-white/80 text-center mb-8">
          {fallo ? (error ?? trabajo.mensaje) : listo ? "Abriendo el resultado…" : `Analizando el comportamiento espectral de ${cropId}…`}
        </p>
        {!fallo && (
          <>
            <div className="w-full bg-white/20 rounded-full h-3 mb-3 overflow-hidden">
              <div className="h-full bg-white rounded-full transition-all duration-500 ease-out" style={{ width: `${pct}%` }} />
            </div>
            <div className="mb-8 tabular-nums">{trabajo.estado === "en_cola" ? "En cola" : `${pct} %`}</div>
            <ol className="w-full space-y-3">
              {PASOS.map((p, k) => {
                const actual = !listo && k === paso, hecho = listo || k < paso;
                const Icono = p.icono;
                return (
                  <li key={p.texto} className={`flex items-center gap-3 p-4 rounded-lg transition-all
                        ${actual ? "bg-white/20 backdrop-blur-sm" : hecho ? "bg-white/5" : ""}`}>
                    <div className={`p-2 rounded-lg ${actual || hecho ? "bg-white/20" : "bg-white/5"}`}>
                      <Icono className={`w-5 h-5 ${actual ? "animate-pulse" : ""}`} />
                    </div>
                    <span className={`flex-1 ${actual ? "" : hecho ? "text-white/60" : "text-white/40"}`}>{p.texto}</span>
                    {hecho && <CheckCircle2 className="w-5 h-5 text-white/70" />}
                  </li>
                );
              })}
            </ol>
          </>
        )}
        {fallo && (
          <button className="mt-2 inline-flex items-center gap-2 px-5 py-3 rounded-lg bg-white text-[#1a5c1a] font-medium"
                  onClick={onReintentar}>
            <RotateCcw className="w-5 h-5" /> Volver e intentar de nuevo
          </button>
        )}
        <div className="mt-10 grid grid-cols-3 gap-3 w-full">
          {[["Bandas", "10"], ["Resolución", "10 m"], ["Palma", area ? ha(area) : "—"]].map(([t, v]) => (
            <div key={t} className="cristal p-3 text-center">
              <div className="text-white/70 text-sm mb-1">{t}</div>
              <div className="font-semibold">{v}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
