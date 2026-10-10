import { useCallback, useEffect, useState } from "react";
import { BarChart3, History, Home, LogOut, Plus, Sprout, User } from "lucide-react";
import { api, fijarAlExpirarSesion, type Estado, type Usuario } from "./api";
import { iniciales } from "./ui";
import Ingreso from "./vistas/Ingreso";
import Inicio from "./vistas/Inicio";
import Plantacion from "./vistas/Plantacion";
import NuevoAnalisis from "./vistas/NuevoAnalisis";
import Historial from "./vistas/Historial";
import Estadisticas from "./vistas/Estadisticas";
import Perfil from "./vistas/Perfil";

export type Vista = "inicio" | "historial" | "estadisticas" | "perfil" | "plantacion" | "nuevo";
export interface Ruta { vista: Vista; plantacion?: string; escena?: string }
export type Navegar = (r: Ruta) => void;
export type Tema = "claro" | "oscuro";

const PESTANAS: { vista: Vista; etiqueta: string; icono: typeof Home }[] = [
  { vista: "inicio", etiqueta: "Inicio", icono: Home },
  { vista: "historial", etiqueta: "Historial", icono: History },
  { vista: "estadisticas", etiqueta: "Estadísticas", icono: BarChart3 },
  { vista: "perfil", etiqueta: "Perfil", icono: User },
];

// La URL guarda la vista (enlace directo y botón "atrás" del navegador):
// ?plantacion=PALMA_0001&escena=PALMA_0001_2025-04-14 abre esa plantación en esa fecha.
function rutaDeUrl(): Ruta {
  const q = new URLSearchParams(window.location.search);
  const plantacion = q.get("plantacion") ?? undefined;
  const vista = (q.get("vista") as Vista | null) ?? (plantacion ? "plantacion" : "inicio");
  return { vista: PESTANAS.some((p) => p.vista === vista) || vista === "plantacion" || vista === "nuevo"
    ? vista : "inicio", plantacion, escena: q.get("escena") ?? undefined };
}

function urlDeRuta(r: Ruta): string {
  const q = new URLSearchParams();
  if (r.vista !== "inicio" && r.vista !== "plantacion") q.set("vista", r.vista);
  if (r.plantacion) q.set("plantacion", r.plantacion);
  if (r.escena) q.set("escena", r.escena);
  const t = q.toString();
  return t ? `?${t}` : window.location.pathname;
}

export function aplicarTema(t: Tema) {
  document.documentElement.classList.toggle("dark", t === "oscuro");
  try { localStorage.setItem("tema", t); } catch { /* almacenamiento bloqueado */ }
}

export function temaGuardado(): Tema {
  try {
    const t = localStorage.getItem("tema");
    if (t === "claro" || t === "oscuro") return t;
  } catch { /* almacenamiento bloqueado */ }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
}

export default function App() {
  const [usuario, setUsuario] = useState<Usuario | null | undefined>(undefined);  // undefined = verificando
  const [estado, setEstado] = useState<Estado | null>(null);
  const [ruta, setRuta] = useState<Ruta>(rutaDeUrl);
  const [tema, setTema] = useState<Tema>(temaGuardado);

  useEffect(() => {
    fijarAlExpirarSesion(() => setUsuario(null));
    api.yo().then(setUsuario).catch(() => setUsuario(null));
    const atras = () => setRuta(rutaDeUrl());
    window.addEventListener("popstate", atras);
    return () => window.removeEventListener("popstate", atras);
  }, []);

  useEffect(() => {
    if (usuario) api.estado().then(setEstado).catch(() => setEstado(null));
  }, [usuario]);

  const navegar = useCallback<Navegar>((r) => {
    setRuta(r);
    const url = urlDeRuta(r);
    const actual = window.location.search || window.location.pathname;
    if (url !== actual) window.history.pushState(null, "", url);
    window.scrollTo({ top: 0 });
  }, []);

  // Cambiar de fecha dentro de una plantación no crea una entrada nueva en el historial del navegador.
  const reemplazar = useCallback<Navegar>((r) => {
    setRuta(r);
    window.history.replaceState(null, "", urlDeRuta(r));
  }, []);

  const cambiarTema = (t: Tema) => { aplicarTema(t); setTema(t); };

  const salir = async () => {
    await api.salir().catch(() => {});
    setUsuario(null);
    navegar({ vista: "inicio" });
  };

  if (usuario === undefined) return <Bienvenida />;
  if (usuario === null) return <Ingreso onIngreso={setUsuario} />;

  const demo = !!estado?.modelos?.demo;
  const pestana = ruta.vista === "plantacion" || ruta.vista === "nuevo" ? null : ruta.vista;

  return (
    <div className="min-h-dvh lg:flex">
      {/* Escritorio: barra lateral */}
      <aside className="hidden lg:flex lg:flex-col w-64 shrink-0 h-dvh sticky top-0 border-r border-borde bg-tarjeta">
        <div className="flex items-center gap-3 px-6 h-20">
          <div className="p-2 bg-agro rounded-xl"><Sprout className="w-6 h-6 text-white" /></div>
          <div>
            <div className="text-lg font-semibold text-agro leading-tight">AgroSpec</div>
            <div className="text-xs text-tenue">Palma de aceite · Santander</div>
          </div>
        </div>
        <div className="px-4">
          <button className="boton w-full" onClick={() => navegar({ vista: "nuevo" })}>
            <Plus className="w-5 h-5" /> Nuevo análisis
          </button>
        </div>
        <nav className="flex-1 px-3 py-6 space-y-1" aria-label="Principal">
          {PESTANAS.map(({ vista, etiqueta, icono: Icono }) => (
            <button key={vista} onClick={() => navegar({ vista })} aria-current={pestana === vista ? "page" : undefined}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-lg transition-colors text-left
                      ${pestana === vista ? "bg-agro/10 text-agro font-medium" : "text-tenue hover:bg-suave hover:text-texto"}`}>
              <Icono className="w-5 h-5" /> {etiqueta}
            </button>
          ))}
        </nav>
        {demo && (
          <div className="mx-4 mb-3 p-3 rounded-lg bg-[#7c3aed]/10 text-xs text-[#7c3aed] dark:text-[#c4b5fd]">
            Modelos <strong>DEMO</strong>: resultados de prueba, no de la tesis.
          </div>
        )}
        <div className="border-t border-borde p-4 flex items-center gap-3">
          <button onClick={() => navegar({ vista: "perfil" })}
                  className="w-10 h-10 shrink-0 rounded-full bg-agro/15 text-agro font-semibold flex items-center justify-center">
            {iniciales(usuario.nombre)}
          </button>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium truncate">{usuario.nombre}</div>
            <div className="text-xs text-tenue truncate">{usuario.correo}</div>
          </div>
          <button onClick={salir} aria-label="Cerrar sesión" title="Cerrar sesión"
                  className="p-2 rounded-lg text-tenue hover:bg-suave hover:text-texto">
            <LogOut className="w-5 h-5" />
          </button>
        </div>
      </aside>

      <main className={`flex-1 min-w-0 ${pestana ? "pb-24 lg:pb-10" : "pb-10"}`}>
        {demo && (
          <div className="lg:hidden bg-[#7c3aed] text-white text-xs text-center px-4 py-1.5">
            Modelos DEMO: resultados de prueba, no de la tesis
          </div>
        )}
        <div className="lg:px-8 mx-auto max-w-7xl">
          {ruta.vista === "inicio" && <Inicio usuario={usuario} navegar={navegar} />}
          {ruta.vista === "plantacion" && ruta.plantacion && (
            <Plantacion cropId={ruta.plantacion} escenaInicial={ruta.escena} estado={estado} tema={tema}
                        navegar={navegar} reemplazar={reemplazar} />
          )}
          {ruta.vista === "nuevo" && (
            <NuevoAnalisis estado={estado} plantacionInicial={ruta.plantacion} navegar={navegar} />
          )}
          {ruta.vista === "historial" && <Historial navegar={navegar} />}
          {ruta.vista === "estadisticas" && <Estadisticas tema={tema} navegar={navegar} />}
          {ruta.vista === "perfil" && (
            <Perfil usuario={usuario} estado={estado} tema={tema} onTema={cambiarTema} onSalir={salir} />
          )}
        </div>
      </main>

      {/* Celular y tableta: barra inferior, como en el diseño */}
      {pestana && (
        <nav aria-label="Principal"
             className="lg:hidden fixed bottom-0 inset-x-0 z-[1000] bg-tarjeta/95 backdrop-blur border-t border-borde zona-segura">
          <div className="flex items-center justify-around px-2 py-2 max-w-xl mx-auto">
            {PESTANAS.slice(0, 2).map((p) => <Pestana key={p.vista} {...p} activa={pestana === p.vista} navegar={navegar} />)}
            <button onClick={() => navegar({ vista: "nuevo" })} aria-label="Nuevo análisis"
                    className="-mt-8 w-14 h-14 rounded-full bg-agro text-white shadow-lg flex items-center justify-center
                               ring-4 ring-fondo hover:bg-agro-dark transition-colors">
              <Plus className="w-7 h-7" />
            </button>
            {PESTANAS.slice(2).map((p) => <Pestana key={p.vista} {...p} activa={pestana === p.vista} navegar={navegar} />)}
          </div>
        </nav>
      )}
    </div>
  );
}

function Pestana({ vista, etiqueta, icono: Icono, activa, navegar }:
  { vista: Vista; etiqueta: string; icono: typeof Home; activa: boolean; navegar: Navegar }) {
  return (
    <button onClick={() => navegar({ vista })} aria-current={activa ? "page" : undefined}
            className={`flex flex-col items-center gap-1 px-3 sm:px-5 py-1.5 rounded-lg transition-colors min-w-16
              ${activa ? "text-agro bg-agro/10" : "text-tenue hover:bg-suave"}`}>
      <Icono className="w-6 h-6" />
      <span className="text-xs">{etiqueta === "Estadísticas" ? "Stats" : etiqueta}</span>
    </button>
  );
}

/** Pantalla de bienvenida (splash del diseño) mientras se verifica la sesión. */
function Bienvenida() {
  return (
    <div className="h-dvh flex flex-col items-center justify-center bg-gradient-to-b from-[#2d7a2d] to-[#1a5c1a] text-white">
      <div className="mb-6 p-6 bg-white/10 rounded-full backdrop-blur-sm">
        <Sprout className="w-20 h-20" strokeWidth={1.5} />
      </div>
      <h1 className="text-3xl mb-2">AgroSpec</h1>
      <p className="text-white/90 text-center px-8">Detección temprana de anomalías en palma de aceite</p>
      <div className="mt-12 flex gap-2" aria-label="Cargando">
        {[0, 200, 400].map((d) => (
          <span key={d} className="w-2 h-2 bg-white rounded-full animate-pulse" style={{ animationDelay: `${d}ms` }} />
        ))}
      </div>
    </div>
  );
}
