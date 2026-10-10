import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Calendar, Leaf, Map as MapaIcono, Plus, Search, Sprout } from "lucide-react";
import type { Navegar } from "../App";
import { api, type Ubicacion, type Usuario } from "../api";
import { Aviso, Cabecera, Cargando, fechaLarga, ha, iniciales, InsigniaEstado, Miniatura, nombreClase, num } from "../ui";
import MapaGeneral from "../components/MapaGeneral";

type Orden = "revisar" | "reciente" | "codigo";
const POR_PAGINA = 12;
const PESO = { revisar: 0, puntual: 1, sin_anomalias: 2 } as const;

export default function Inicio({ usuario, navegar }: { usuario: Usuario; navegar: Navegar }) {
  const [ubic, setUbic] = useState<Ubicacion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [texto, setTexto] = useState("");
  const [clase, setClase] = useState("");
  const [orden, setOrden] = useState<Orden>("revisar");
  const [visibles, setVisibles] = useState(POR_PAGINA);

  useEffect(() => {
    api.ubicaciones().then(setUbic).catch((e) => setError(e.message));
  }, []);

  const lista = useMemo(() => {
    const t = texto.trim().toLowerCase();
    return (ubic ?? [])
      .filter((u) => (!t || u.crop_id.toLowerCase().includes(t)) && (!clase || u.clase === clase))
      .sort((a, b) => {
        if (orden === "codigo") return a.crop_id.localeCompare(b.crop_id);
        if (orden === "reciente") return (b.ultima?.fecha ?? "").localeCompare(a.ultima?.fecha ?? "");
        const pa = a.ultima ? PESO[a.ultima.estado] : 3, pb = b.ultima ? PESO[b.ultima.estado] : 3;
        return pa - pb || (b.ultima?.pct_consenso ?? 0) - (a.ultima?.pct_consenso ?? 0);
      });
  }, [ubic, texto, clase, orden]);

  const aRevisar = (ubic ?? []).filter((u) => u.ultima?.estado === "revisar");
  const haPalma = (ubic ?? []).reduce((s, u) => s + (u.ha_palma_ref ?? 0), 0);
  const prioritaria = [...aRevisar].sort((a, b) => b.ultima!.ha_consenso - a.ultima!.ha_consenso)[0];
  const nombre = usuario.nombre.split(" ")[0];

  return (
    <>
      <Cabecera titulo={`Hola, ${nombre}`} subtitulo={usuario.municipio ? `${usuario.municipio}, Santander` : "Santander"}
                accion={
                  <button onClick={() => navegar({ vista: "perfil" })} aria-label="Perfil"
                          className="lg:hidden w-10 h-10 bg-white/20 rounded-full flex items-center justify-center backdrop-blur-sm font-semibold">
                    {iniciales(usuario.nombre)}
                  </button>
                }>
        <div className="grid grid-cols-3 gap-2 sm:gap-3 mt-6">
          <Dato titulo="Plantaciones" valor={ubic ? String(ubic.length) : "…"} />
          <Dato titulo="Palma" valor={ubic ? ha(haPalma) : "…"} />
          <Dato titulo="A revisar" valor={ubic ? String(aRevisar.length) : "…"} />
        </div>
      </Cabecera>

      <div className="px-4 sm:px-6 lg:px-0 py-6 space-y-6">
        {error && <Aviso tipo="error" titulo="No se pudo cargar el catálogo">{error}</Aviso>}

        {prioritaria && (
          <div className="p-4 rounded-xl border border-rojo/25 bg-gradient-to-r from-rojo/10 to-amarillo/10 flex gap-3 aparecer">
            <div className="p-2 h-fit bg-rojo text-white rounded-lg"><AlertTriangle className="w-5 h-5" /></div>
            <div className="flex-1 min-w-0">
              <h4 className="mb-1">Prioridad de visita: {prioritaria.crop_id}</h4>
              <p className="text-sm text-tenue">
                El {fechaLarga(prioritaria.ultima!.fecha)} el consenso de detectores marcó{" "}
                <strong className="text-texto">{ha(prioritaria.ultima!.ha_consenso)}</strong> ({num(prioritaria.ultima!.pct_consenso)} %
                de la palma evaluable) en {prioritaria.ultima!.n_regiones} regiones. Verifique en campo.
              </p>
              <button className="mt-2 text-sm font-medium text-agro hover:underline"
                      onClick={() => navegar({ vista: "plantacion", plantacion: prioritaria.crop_id, escena: prioritaria.ultima!.id })}>
                Ver regiones en el mapa →
              </button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_380px]">
          <section>
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
              <h3>Plantaciones monitoreadas</h3>
              <button onClick={() => navegar({ vista: "nuevo" })} className="boton py-2 hidden sm:inline-flex">
                <Plus className="w-5 h-5" /> Nuevo análisis
              </button>
            </div>
            <div className="flex flex-col sm:flex-row gap-2 mb-4">
              <label className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-tenue" />
                <input type="search" className="campo pl-11 py-2.5" placeholder="Buscar código (p. ej. PALMA_0031)"
                       value={texto} onChange={(e) => { setTexto(e.target.value); setVisibles(POR_PAGINA); }}
                       aria-label="Buscar plantación" />
              </label>
              <div className="flex gap-2">
                <select className="campo py-2.5 sm:w-44" value={clase} aria-label="Tipo de productor"
                        onChange={(e) => { setClase(e.target.value); setVisibles(POR_PAGINA); }}>
                  <option value="">Todos los tipos</option>
                  <option value="industrial">Industrial</option>
                  <option value="smallholder">Pequeño productor</option>
                </select>
                <select className="campo py-2.5 sm:w-44" value={orden} aria-label="Ordenar"
                        onChange={(e) => setOrden(e.target.value as Orden)}>
                  <option value="revisar">Prioridad</option>
                  <option value="reciente">Más reciente</option>
                  <option value="codigo">Por código</option>
                </select>
              </div>
            </div>

            {!ubic && !error && <Cargando texto="Cargando plantaciones…" />}
            {ubic && !lista.length && (
              <div className="tarjeta p-8 text-center text-tenue">
                <Leaf className="w-10 h-10 mx-auto mb-3 text-agro" />
                {ubic.length ? "Ninguna plantación coincide con la búsqueda." : "Aún no hay plantaciones. Corra el precálculo (ver README)."}
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
              {lista.slice(0, visibles).map((u) => <TarjetaPlantacion key={u.crop_id} u={u} navegar={navegar} />)}
            </div>
            {lista.length > visibles && (
              <button className="boton-borde w-full mt-4" onClick={() => setVisibles(visibles + POR_PAGINA)}>
                Mostrar más ({lista.length - visibles} restantes)
              </button>
            )}
          </section>

          <aside className="space-y-4">
            <div className="tarjeta overflow-hidden xl:sticky xl:top-6">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-borde">
                <MapaIcono className="w-5 h-5 text-agro" /><h4>Mapa de plantaciones</h4>
              </div>
              <div className="h-72 sm:h-80 xl:h-[420px]">
                {ubic && <MapaGeneral ubicaciones={ubic}
                                      onPlantacion={(u) => navegar({ vista: "plantacion", plantacion: u })} />}
              </div>
              <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-3 text-xs text-tenue border-t border-borde">
                <Punto color="var(--agro-green)" texto="Sin anomalías" />
                <Punto color="var(--agro-yellow)" texto="Puntual" />
                <Punto color="var(--agro-red)" texto="Revisar" />
              </div>
            </div>
          </aside>
        </div>
      </div>
    </>
  );
}

function Dato({ titulo, valor }: { titulo: string; valor: string }) {
  return (
    <div className="cristal p-3 sm:p-4">
      <div className="text-white/70 text-xs sm:text-sm mb-1">{titulo}</div>
      <div className="text-white text-lg sm:text-xl font-semibold truncate">{valor}</div>
    </div>
  );
}

function Punto({ color, texto }: { color: string; texto: string }) {
  return <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />{texto}</span>;
}

function TarjetaPlantacion({ u, navegar }: { u: Ubicacion; navegar: Navegar }) {
  const abrir = () => navegar({ vista: "plantacion", plantacion: u.crop_id, escena: u.ultima?.id });
  return (
    <button onClick={abrir}
            className="tarjeta overflow-hidden text-left shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all aparecer">
      <div className="relative">
        <Miniatura escenaId={u.ultima?.id} alt={`Imagen de ${u.crop_id}`} className="h-36" />
        <div className="absolute top-3 right-3"><InsigniaEstado estado={u.ultima?.estado} solida /></div>
      </div>
      <div className="p-4">
        <h4 className="mb-1">{u.crop_id}</h4>
        <div className="flex items-center gap-2 text-sm text-tenue">
          <Sprout className="w-4 h-4" /> {nombreClase(u.clase)} <span>•</span> {ha(u.ha_palma_ref)} de palma
        </div>
        <div className="flex items-center justify-between pt-3 mt-3 border-t border-borde text-sm">
          <span className="flex items-center gap-2 text-tenue">
            <Calendar className="w-4 h-4" /> {u.ultima ? fechaLarga(u.ultima.fecha) : "Sin fechas"}
          </span>
          <span className="px-2.5 py-1 bg-suave rounded-lg">NDVI {num(u.ultima?.ndvi_mediana)}</span>
        </div>
      </div>
    </button>
  );
}
