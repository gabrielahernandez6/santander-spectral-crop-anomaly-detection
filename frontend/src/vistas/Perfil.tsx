import { useEffect, useState, type ReactNode } from "react";
import { Calendar, Cpu, Info, LogOut, Mail, MapPin, Moon, Sprout, Sun, User } from "lucide-react";
import type { Tema } from "../App";
import { api, type Estado, type Estadisticas, type Usuario } from "../api";
import { Aviso, ha, iniciales } from "../ui";

interface Props {
  usuario: Usuario;
  estado: Estado | null;
  tema: Tema;
  onTema: (t: Tema) => void;
  onSalir: () => void;
}

export default function Perfil({ usuario, estado, tema, onTema, onSalir }: Props) {
  const [stats, setStats] = useState<Estadisticas | null>(null);
  useEffect(() => { api.estadisticas().then(setStats).catch(() => setStats(null)); }, []);
  const oscuro = tema === "oscuro";
  const m = estado?.modelos;
  const desde = new Date(usuario.creado * 1000).toLocaleDateString("es-CO", { day: "numeric", month: "long", year: "numeric" });

  return (
    <>
      <header className="cabecera px-6 pt-10 pb-8 lg:rounded-2xl lg:mt-6">
        <div className="flex flex-col items-center">
          <div className="w-24 h-24 bg-white/20 rounded-full flex items-center justify-center backdrop-blur-sm mb-4 text-3xl font-semibold">
            {iniciales(usuario.nombre)}
          </div>
          <h2 className="text-white mb-1 text-center">{usuario.nombre}</h2>
          <p className="text-white/80 break-all text-center">{usuario.correo}</p>
        </div>
      </header>

      <div className="px-4 sm:px-6 lg:px-0 py-6 grid grid-cols-1 gap-6 lg:grid-cols-2 items-start">
        <div className="space-y-6">
          <div className="tarjeta p-4 grid grid-cols-3 gap-4 text-center">
            <Cifra valor={stats ? String(stats.n_plantaciones) : "…"} texto="Plantaciones" />
            <Cifra valor={stats ? ha(stats.ha_palma) : "…"} texto="Palma" />
            <Cifra valor={stats ? String(stats.n_analisis) : "…"} texto="Análisis" />
          </div>

          <section>
            <h3 className="mb-3">Información personal</h3>
            <div className="tarjeta overflow-hidden divide-y divide-borde">
              <Fila icono={<User />} titulo="Nombre">{usuario.nombre}</Fila>
              <Fila icono={<Mail />} titulo="Correo"><span className="break-all">{usuario.correo}</span></Fila>
              <Fila icono={<MapPin />} titulo="Municipio">{usuario.municipio ? `${usuario.municipio}, Santander` : "Sin definir"}</Fila>
              <Fila icono={<Calendar />} titulo="Miembro desde">{desde}</Fila>
            </div>
          </section>

          <section>
            <h3 className="mb-3">Configuración</h3>
            <div className="tarjeta overflow-hidden divide-y divide-borde">
              <button onClick={() => onTema(oscuro ? "claro" : "oscuro")} role="switch" aria-checked={oscuro}
                      className="flex items-center gap-3 p-4 w-full hover:bg-suave transition-colors text-left">
                {oscuro ? <Sun className="w-5 h-5 text-tenue" /> : <Moon className="w-5 h-5 text-tenue" />}
                <span className="flex-1">Modo oscuro</span>
                <span className={`w-12 h-6 rounded-full relative transition-colors ${oscuro ? "bg-agro" : "bg-suave border border-borde"}`}>
                  <span className={`absolute top-1 w-4 h-4 bg-white rounded-full shadow transition-transform
                                    ${oscuro ? "translate-x-7" : "translate-x-1"}`} />
                </span>
              </button>
              <button onClick={onSalir} className="flex items-center gap-3 p-4 w-full hover:bg-rojo/10 text-rojo transition-colors text-left">
                <LogOut className="w-5 h-5" /><span className="flex-1">Cerrar sesión</span>
              </button>
            </div>
          </section>
        </div>

        <div className="space-y-6">
          <section>
            <h3 className="mb-3">Acerca de</h3>
            <div className="tarjeta p-4">
              <div className="flex items-center gap-3 mb-3">
                <div className="p-2 bg-agro/10 rounded-lg"><Sprout className="w-8 h-8 text-agro" /></div>
                <div>
                  <div className="font-semibold">AgroSpec</div>
                  <div className="text-sm text-tenue">Versión 1.0.0 · prototipo del proyecto de grado</div>
                </div>
              </div>
              <p className="text-sm text-tenue">
                Detección temprana de anomalías espectrales en palma de aceite con imágenes Sentinel-2: índices
                espectrales, segmentación U-Net y seis detectores (One-Class SVM, Isolation Forest, LOF, SimCLR, BYOL y
                autoencoder) con consenso por votos.
              </p>
            </div>
          </section>

          <section>
            <h3 className="mb-3">Modelos</h3>
            <div className="tarjeta overflow-hidden divide-y divide-borde">
              <Fila icono={<Cpu />} titulo="Estado">
                {!estado ? "…" : !estado.modelos_cargados ? <span className="text-rojo">No cargados</span>
                  : m?.demo ? <span className="text-[#7c3aed] dark:text-[#c4b5fd]">Paquete DEMO (solo pruebas)</span>
                  : <span className="text-agro">Paquete definitivo</span>}
              </Fila>
              {m && (
                <>
                  <Fila icono={<Info />} titulo="Consenso">{m.consenso_min} de {m.detectores.length} detectores</Fila>
                  <Fila icono={<Info />} titulo="Versiones">
                    <span className="text-sm">{Object.entries(m.versiones).map(([k, v]) => `${k} ${v}`).join(" · ")}</span>
                  </Fila>
                </>
              )}
            </div>
          </section>

          <Aviso tipo="alerta" titulo="Importante">
            Una anomalía espectral <strong>no es un diagnóstico</strong>. Indica dónde inspeccionar; la causa (riego,
            nutrición, sanidad u otra) debe confirmarse en campo.
          </Aviso>
        </div>
      </div>
    </>
  );
}

function Cifra({ valor, texto }: { valor: string; texto: string }) {
  return (
    <div className="min-w-0">
      <div className="text-agro font-semibold text-lg truncate">{valor}</div>
      <div className="text-xs sm:text-sm text-tenue">{texto}</div>
    </div>
  );
}

function Fila({ icono, titulo, children }: { icono: ReactNode; titulo: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 p-4">
      <span className="text-tenue [&>svg]:w-5 [&>svg]:h-5 shrink-0">{icono}</span>
      <div className="flex-1 min-w-0">
        <div className="text-xs text-tenue">{titulo}</div>
        <div>{children}</div>
      </div>
    </div>
  );
}
