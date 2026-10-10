import { useEffect } from "react";
import { GeoJSON, ImageOverlay, LayersControl, MapContainer, Marker, Rectangle, TileLayer, useMap,
  useMapEvents } from "react-leaflet";
import L from "leaflet";
import { api, type Pixel, type PropiedadesRegion, type Regiones, type Resumen, type Ubicacion } from "../api";
import { ORDEN_CAPAS, type EstadoCapas } from "./PanelCapas";
import { SANTANDER, TESELAS } from "./mapaComun";

interface Props {
  ubicacion: Ubicacion | null;
  resumen: Resumen | null;
  escenaId: string | null;
  capas: EstadoCapas;
  regiones: Regiones | null;
  regionSeleccionada: number | null;
  pixel: Pixel | null;
  onRegion: (r: PropiedadesRegion) => void;
  onPixel: (lat: number, lon: number) => void;
}

const icono = L.divIcon({ className: "marca-pixel", iconSize: [14, 14] });

function Encuadre({ limites }: { limites: L.LatLngBoundsExpression | null }) {
  const mapa = useMap();
  useEffect(() => {
    mapa.fitBounds(limites ?? SANTANDER, { padding: [16, 16] });
  }, [mapa, limites]);
  return null;
}

/** Leaflet no se entera cuando su contenedor cambia de tamaño por el diseño responsive (no por la ventana). */
function AjustarTamano() {
  const mapa = useMap();
  useEffect(() => {
    const obs = new ResizeObserver(() => mapa.invalidateSize());
    obs.observe(mapa.getContainer());
    return () => obs.disconnect();
  }, [mapa]);
  return null;
}

function Clics({ activo, onPixel }: { activo: boolean; onPixel: (lat: number, lon: number) => void }) {
  useMapEvents({ click: (e) => activo && onPixel(e.latlng.lat, e.latlng.lng) });
  return null;
}

export default function Mapa(p: Props) {
  const limites = (p.ubicacion?.limites ?? null) as L.LatLngBoundsExpression | null;
  const capasVisibles = p.resumen ? ORDEN_CAPAS(p.resumen.capas, p.capas).filter((c) => c.visible) : [];

  return (
    <MapContainer className="h-full w-full" bounds={SANTANDER} zoomSnap={0.25} preferCanvas>
      <LayersControl position="bottomright">
        <LayersControl.BaseLayer checked name="Satélite (Esri)"><TileLayer {...TESELAS.satelite} /></LayersControl.BaseLayer>
        <LayersControl.BaseLayer name="Mapa (OpenStreetMap)"><TileLayer {...TESELAS.calles} /></LayersControl.BaseLayer>
      </LayersControl>
      <Encuadre limites={limites} />
      <AjustarTamano />
      <Clics activo={!!p.escenaId} onPixel={p.onPixel} />

      {p.ubicacion && !p.resumen && (
        <Rectangle bounds={p.ubicacion.limites} pathOptions={{ color: "#fff", weight: 1.5, fillOpacity: 0 }} />
      )}

      {p.resumen && p.escenaId && capasVisibles.map((c) => (
        <ImageOverlay key={`${p.escenaId}-${c.id}`} url={api.urlCapa(p.escenaId!, c.id)}
                      bounds={p.resumen!.limites} opacity={c.opacidad} className="capa-pixelada" />
      ))}

      {p.regiones && p.escenaId && p.capas.contornos && (
        <GeoJSON key={`${p.escenaId}-${p.regionSeleccionada}`} data={p.regiones}
                 style={(f) => ({
                   color: f?.properties.region === p.regionSeleccionada ? "#22d3ee" : "#fde047",
                   weight: f?.properties.region === p.regionSeleccionada ? 3 : 1.5, fillOpacity: 0,
                 })}
                 onEachFeature={(f, capa) => {
                   capa.on("click", (e) => { L.DomEvent.stopPropagation(e); p.onRegion(f.properties); });
                   capa.bindTooltip(`Región ${f.properties.region} · ${f.properties.ha} ha`);
                 }} />
      )}
      {p.pixel && <Marker position={[p.pixel.lat, p.pixel.lon]} icon={icono} />}
    </MapContainer>
  );
}
