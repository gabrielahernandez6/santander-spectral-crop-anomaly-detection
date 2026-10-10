import type L from "leaflet";
import type { EstadoEscena } from "../api";

export const SANTANDER: L.LatLngBoundsExpression = [[5.7, -74.55], [8.15, -72.45]];

// Leaflet dibuja en SVG con atributos, que no aceptan var(--x): los colores van como valores.
export const COLOR_ESTADO: Record<EstadoEscena, string> = {
  sin_anomalias: "#3fa34d",
  puntual: "#f5c842",
  revisar: "#e74c3c",
};

export const TESELAS = {
  satelite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imágenes &copy; Esri", maxZoom: 19,
  },
  calles: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "&copy; colaboradores de OpenStreetMap", maxZoom: 19,
  },
};
