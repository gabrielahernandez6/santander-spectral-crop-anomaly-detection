import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import App, { aplicarTema, temaGuardado } from "./App";

// El tema se aplica antes del primer render para que no parpadee ni lean colores viejos los gráficos.
aplicarTema(temaGuardado());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
