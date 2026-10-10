import { useEffect } from "react";
import { CircleMarker, MapContainer, Rectangle, TileLayer, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import type { Ubicacion } from "../api";
import { COLOR_ESTADO, SANTANDER, TESELAS } from "./mapaComun";

/** Todas las plantaciones del catálogo, coloreadas por el semáforo de su fecha más reciente. */
export default function MapaGeneral({ ubicaciones, onPlantacion }:
  { ubicaciones: Ubicacion[]; onPlantacion: (cropId: string) => void }) {
  return (
    <MapContainer className="h-full w-full" bounds={SANTANDER} zoomSnap={0.25} scrollWheelZoom={false}>
      <TileLayer {...TESELAS.satelite} />
      <Encuadre ubicaciones={ubicaciones} />
      {ubicaciones.map((u) => {
        const color = u.ultima ? COLOR_ESTADO[u.ultima.estado] : "#94a3b8";
        return (
          <FragmentoPlantacion key={u.crop_id} u={u} color={color} onClick={() => onPlantacion(u.crop_id)} />
        );
      })}
    </MapContainer>
  );
}

function FragmentoPlantacion({ u, color, onClick }: { u: Ubicacion; color: string; onClick: () => void }) {
  const eventos = { click: onClick };
  return (
    <>
      <Rectangle bounds={u.limites} pathOptions={{ color, weight: 1.5, fillOpacity: 0.12 }} eventHandlers={eventos} />
      <CircleMarker center={u.centro} radius={7} eventHandlers={eventos}
                    pathOptions={{ color: "#fff", weight: 2, fillColor: color, fillOpacity: 1 }}>
        <Tooltip direction="top" offset={[0, -6]}>
          <strong>{u.crop_id}</strong><br />{u.n_fechas} fechas · clic para abrir
        </Tooltip>
      </CircleMarker>
    </>
  );
}

function Encuadre({ ubicaciones }: { ubicaciones: Ubicacion[] }) {
  const mapa = useMap();
  useEffect(() => {
    if (!ubicaciones.length) return;
    const b = L.latLngBounds(ubicaciones.flatMap((u) => u.limites));
    mapa.fitBounds(b, { padding: [28, 28], maxZoom: 13 });
  }, [mapa, ubicaciones]);
  return null;
}
