import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import L from "leaflet";
import { MapContainer, TileLayer, useMap } from "react-leaflet";
import { CARTHAGE_CENTER, CARTHAGE_DEFAULT_ZOOM } from "./mapUtils";
import { positionsSignature } from "./mapVisibility";

interface FitBoundsProps {
  positions: [number, number][];
}

/**
 * Fits the camera to `positions`, but only once per distinct geometry.
 * A signature ref guards against refitting when the positions array gets a new
 * reference with identical content (which would otherwise fight the user).
 */
export function FitBounds({ positions }: FitBoundsProps) {
  const map = useMap();
  const lastSignature = useRef<string | null>(null);

  useEffect(() => {
    if (positions.length === 0) return;
    const signature = positionsSignature(positions);
    if (signature === lastSignature.current) return;
    lastSignature.current = signature;

    if (positions.length === 1) {
      map.setView(positions[0], 16);
      return;
    }
    map.fitBounds(L.latLngBounds(positions), { padding: [40, 40] });
  }, [map, positions]);

  return null;
}

interface DourbiaMapProps {
  children?: ReactNode;
  fitPositions?: [number, number][];
  className?: string;
  center?: [number, number];
  zoom?: number;
}

export default function DourbiaMap({
  children,
  fitPositions = [],
  className = "dourbia-leaflet-map",
  center = CARTHAGE_CENTER,
  zoom = CARTHAGE_DEFAULT_ZOOM,
}: DourbiaMapProps) {
  return (
    <MapContainer center={center} zoom={zoom} scrollWheelZoom className={className}>
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      {fitPositions.length > 0 && <FitBounds positions={fitPositions} />}
      {children}
    </MapContainer>
  );
}
