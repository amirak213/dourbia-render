import { useState } from "react";
import DourbiaMap from "../map/DourbiaMap";
import CircuitRouteLayer, { circuitFitPositions } from "../map/CircuitRouteLayer";
import type { CircuitRecommendResponse } from "../../types/circuit";

interface CircuitMapProps {
  result: CircuitRecommendResponse | null;
  onAskGuide?: (question: string) => void;
}

export default function CircuitMap({ result, onAskGuide }: CircuitMapProps) {
  const [routeStatusLabel, setRouteStatusLabel] = useState("");

  if (!result || result.circuit.monuments.length === 0) {
    return (
      <section className="circuit-map card-panel circuit-map-empty">
        <h2>Carte du circuit</h2>
        <p className="circuit-map-subtitle">
          Visualisez votre parcours optimisé avec les monuments numérotés et le tracé routier.
        </p>
        <p>
          Renseignez vos préférences pour générer un circuit personnalisé à Carthage.
        </p>
      </section>
    );
  }

  const fitPositions = circuitFitPositions(result);

  return (
    <section className="circuit-map card-panel circuit-map-dominant">
      <div className="circuit-map-header">
        <h2>Carte du circuit</h2>
        {routeStatusLabel && (
          <span className="circuit-map-note" role="status">
            {routeStatusLabel}
          </span>
        )}
      </div>
      <p className="circuit-map-subtitle">
        Monuments numérotés dans l&apos;ordre de visite · OpenStreetMap · OSRM
      </p>
      <div className="circuit-map-frame">
        <DourbiaMap
          className="circuit-leaflet-map"
          center={fitPositions[0] ?? [36.857, 10.33]}
          zoom={15}
        >
          <CircuitRouteLayer
            result={result}
            onAskGuide={onAskGuide}
            onRouteStatusChange={(_status, label) => setRouteStatusLabel(label)}
          />
        </DourbiaMap>
      </div>
    </section>
  );
}
