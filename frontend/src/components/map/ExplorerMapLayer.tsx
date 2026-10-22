import { useEffect, useRef } from "react";
import L from "leaflet";
import { Marker, Popup, useMap } from "react-leaflet";
import type { MonumentSummary } from "../../types/monument";
import MonumentDetailCard from "../explorer/MonumentDetailCard";
import { markerCategory, type MarkerCategory } from "./mapVisibility";

function monumentIcon(category: MarkerCategory, isSelected: boolean) {
  const classes = ["explorer-marker", `explorer-marker-${category}`];
  if (isSelected) classes.push("explorer-marker-selected-ring");
  return L.divIcon({
    className: "explorer-leaflet-marker",
    html: `<div class="${classes.join(" ")}"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function categoryZIndex(category: MarkerCategory, isSelected: boolean): number {
  if (isSelected) return 1000;
  switch (category) {
    case "desired":
      return 800;
    case "selected":
      return 700;
    case "historical":
      return 500;
    default:
      return 0;
  }
}

interface FlyToMonumentProps {
  monument: MonumentSummary | null;
}

/** Flies to a monument exactly once per new monument id (never re-fires). */
function FlyToMonument({ monument }: FlyToMonumentProps) {
  const map = useMap();
  const prevId = useRef<number | null>(null);

  useEffect(() => {
    if (!monument || monument.id === prevId.current) return;
    prevId.current = monument.id;
    map.flyTo([monument.latitude, monument.longitude], 16, { duration: 0.8 });
  }, [map, monument]);

  return null;
}

interface ExplorerMapLayerProps {
  monuments: MonumentSummary[];
  selectedMonument: MonumentSummary | null;
  desiredIds: ReadonlySet<number>;
  historicalIds: ReadonlySet<number>;
  onSelectMonument: (monument: MonumentSummary) => void;
  onAskGuide: (monument: MonumentSummary) => void;
  onAddToCircuit: (monument: MonumentSummary) => void;
}

export default function ExplorerMapLayer({
  monuments,
  selectedMonument,
  desiredIds,
  historicalIds,
  onSelectMonument,
  onAskGuide,
  onAddToCircuit,
}: ExplorerMapLayerProps) {
  const selectedId = selectedMonument?.id ?? null;

  return (
    <>
      <FlyToMonument monument={selectedMonument} />
      {monuments.map((monument) => {
        const category = markerCategory(monument.id, {
          selectedId,
          desiredIds,
          historicalIds,
        });
        const isSelected = monument.id === selectedId;
        return (
          <Marker
            key={monument.id}
            position={[monument.latitude, monument.longitude]}
            icon={monumentIcon(category, isSelected)}
            zIndexOffset={categoryZIndex(category, isSelected)}
            eventHandlers={{
              click: () => onSelectMonument(monument),
            }}
          >
            <Popup>
              <MonumentDetailCard
                monument={monument}
                compact
                isMustVisit={desiredIds.has(monument.id)}
                onAskGuide={() => onAskGuide(monument)}
                onAddToCircuit={() => onAddToCircuit(monument)}
                onViewOnMap={() => onSelectMonument(monument)}
              />
            </Popup>
          </Marker>
        );
      })}
    </>
  );
}
