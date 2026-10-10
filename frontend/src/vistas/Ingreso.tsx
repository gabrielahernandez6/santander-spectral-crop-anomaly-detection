import { useState, type FormEvent, type ReactNode } from "react";
import { Eye, EyeOff, Layers, Lock, Mail, MapPin, Satellite, ShieldCheck, Sprout, User } from "lucide-react";
import { api, type Usuario } from "../api";

// Municipios de Santander con palma de aceite (zona del Magdalena Medio) y capitales cercanas.
export const MUNICIPIOS = ["Barrancabermeja", "Bucaramanga", "Cimitarra", "El Carmen de Chucurí", "Puerto Parra",
  "Puerto Wilches", "Rionegro", "Sabana de Torres", "San Vicente de Chucurí", "Simacota", "Otro"];

export default function Ingreso({ onIngreso }: { onIngreso: (u: Usuario) => void }) {
  const [modo, setModo] = useState<"ingreso" | "registro">("ingreso");
  const [nombre, setNombre] = useState("");
  const [correo, setCorreo] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [municipio, setMunicipio] = useState("");
  const [ver, setVer] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const enviar = async (ev: FormEvent) => {
    ev.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      onIngreso(modo === "ingreso"
        ? await api.ingresar(correo, contrasena)
        : await api.registrar({ nombre, correo, contrasena, municipio: municipio || undefined }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setEnviando(false);
    }
  };

  const cambiar = (m: typeof modo) => { setModo(m); setError(null); };

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-2">
      {/* Escritorio: panel de presentación */}
      <section className="hidden lg:flex flex-col justify-between p-12 bg-gradient-to-br from-[#2d7a2d] to-[#1a5c1a] text-white relative overflow-hidden">
        <div className="absolute -top-32 -right-32 w-96 h-96 rounded-full bg-white/10 blur-3xl" aria-hidden />
        <div className="absolute -bottom-40 -left-24 w-96 h-96 rounded-full bg-white/10 blur-3xl" aria-hidden />
        <div className="relative flex items-center gap-3">
          <div className="p-2.5 bg-white/15 rounded-xl"><Sprout className="w-7 h-7" /></div>
          <span className="text-xl font-semibold">AgroSpec</span>
        </div>
        <div className="relative max-w-lg">
          <h1 className="text-4xl leading-tight mb-4">Detección temprana de anomalías en palma de aceite</h1>
          <p className="text-white/85 text-lg mb-10">
            Imágenes Sentinel-2, segmentación con U-Net y seis detectores autosupervisados que votan en consenso.
          </p>
          <ul className="space-y-5">
            <Rasgo icono={<Satellite className="w-5 h-5" />} titulo="Índices espectrales"
                   texto="NDVI, GNDVI, NDRE y NDMI por fecha, a 10 m por píxel." />
            <Rasgo icono={<Layers className="w-5 h-5" />} titulo="Consenso de detectores"
                   texto="Una zona se marca solo cuando varios detectores coinciden." />
            <Rasgo icono={<ShieldCheck className="w-5 h-5" />} titulo="Apoyo a la visita de campo"
                   texto="Indica dónde inspeccionar; no reemplaza el diagnóstico agronómico." />
          </ul>
        </div>
        <p className="relative text-sm text-white/70">Proyecto de grado · Santander, Colombia</p>
      </section>

      <section className="min-h-dvh flex flex-col justify-center px-6 py-10 sm:px-10">
        <div className="w-full max-w-md mx-auto aparecer">
          <div className="flex flex-col items-center mb-8 lg:hidden">
            <div className="p-4 bg-agro rounded-2xl mb-4"><Sprout className="w-12 h-12 text-white" /></div>
            <h1 className="text-agro text-3xl">AgroSpec</h1>
            <p className="text-tenue text-center mt-2">Monitoreo inteligente de palma de aceite</p>
          </div>
          <div className="hidden lg:block mb-8">
            <h2 className="text-3xl">{modo === "ingreso" ? "Bienvenido de nuevo" : "Cree su cuenta"}</h2>
            <p className="text-tenue mt-2">
              {modo === "ingreso" ? "Ingrese para revisar sus plantaciones." : "Regístrese para usar el prototipo."}
            </p>
          </div>

          <div className="flex bg-suave rounded-lg p-1 mb-6" role="tablist">
            {(["ingreso", "registro"] as const).map((m) => (
              <button key={m} role="tab" aria-selected={modo === m} onClick={() => cambiar(m)}
                      className={`flex-1 py-2 rounded-md transition-all font-medium
                        ${modo === m ? "bg-tarjeta shadow-sm" : "text-tenue"}`}>
                {m === "ingreso" ? "Iniciar sesión" : "Registrarse"}
              </button>
            ))}
          </div>

          <form onSubmit={enviar} className="space-y-4" noValidate={false}>
            {modo === "registro" && (
              <Campo etiqueta="Nombre completo" icono={<User />}>
                <input className="campo pl-11" type="text" placeholder="Ana Gómez" autoComplete="name" required
                       minLength={2} maxLength={80} value={nombre} onChange={(e) => setNombre(e.target.value)} />
              </Campo>
            )}
            <Campo etiqueta="Correo electrónico" icono={<Mail />}>
              <input className="campo pl-11" type="email" placeholder="correo@ejemplo.com" autoComplete="email"
                     required value={correo} onChange={(e) => setCorreo(e.target.value)} />
            </Campo>
            <Campo etiqueta="Contraseña" icono={<Lock />}>
              <input className="campo pl-11 pr-12" type={ver ? "text" : "password"} placeholder="••••••••" required
                     minLength={modo === "registro" ? 8 : undefined}
                     autoComplete={modo === "ingreso" ? "current-password" : "new-password"}
                     value={contrasena} onChange={(e) => setContrasena(e.target.value)} />
              <button type="button" onClick={() => setVer(!ver)} aria-label={ver ? "Ocultar contraseña" : "Mostrar contraseña"}
                      className="absolute right-2 top-1/2 -translate-y-1/2 p-2 text-tenue hover:text-texto">
                {ver ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
              </button>
            </Campo>
            {modo === "registro" && (
              <>
                <p className="text-xs text-tenue -mt-2">Mínimo 8 caracteres.</p>
                <Campo etiqueta="Municipio (opcional)" icono={<MapPin />}>
                  <select className="campo pl-11 appearance-none" value={municipio}
                          onChange={(e) => setMunicipio(e.target.value)}>
                    <option value="">Seleccione municipio</option>
                    {MUNICIPIOS.map((m) => <option key={m}>{m}</option>)}
                  </select>
                </Campo>
              </>
            )}

            {error && <p role="alert" className="text-sm text-rojo bg-rojo/10 rounded-lg px-4 py-3">{error}</p>}

            <button type="submit" className="boton w-full" disabled={enviando}>
              {enviando && <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />}
              {modo === "ingreso" ? "Iniciar sesión" : "Crear cuenta"}
            </button>
          </form>

          <p className="text-xs text-tenue text-center mt-8">
            Una anomalía espectral <strong>no es un diagnóstico</strong>: indica dónde mirar y debe verificarse en campo.
          </p>
        </div>
      </section>
    </div>
  );
}

function Campo({ etiqueta, icono, children }: { etiqueta: string; icono: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="etiqueta">{etiqueta}</span>
      <span className="relative block">
        <span className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-tenue [&>svg]:w-5 [&>svg]:h-5 pointer-events-none">
          {icono}
        </span>
        {children}
      </span>
    </label>
  );
}

function Rasgo({ icono, titulo, texto }: { icono: ReactNode; titulo: string; texto: string }) {
  return (
    <li className="flex gap-4">
      <div className="p-2.5 h-fit bg-white/15 rounded-lg">{icono}</div>
      <div>
        <div className="font-semibold">{titulo}</div>
        <div className="text-white/80 text-sm">{texto}</div>
      </div>
    </li>
  );
}
