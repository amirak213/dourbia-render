import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { Marker, Polyline, Popup, useMap } from "react-leaflet";
import { getOsrmRoute } from "../../services/osrmApi";
import { positionsSignature } from "./mapVisibility";
import type { CircuitRecommendResponse } from "../../types/circuit";

type RouteTraceStatus = "idle" | "loading" | "osrm" | "fallback";

function numberedIcon(order: number) {
  return L.divIcon({
    className: "circuit-leaflet-marker",
    html: `<div class="circuit-marker-pin">${order}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function routeStatusLabel(status: RouteTraceStatus): string {
  switch (status) {
    case "loading":
      return "Calcul du tracé routier…";
    case "osrm":
      return "Tracé routier via OSRM";
    case "fallback":
      return "Tracé indicatif";
    default:
      return "";
  }
}

interface CircuitRouteLayerProps {
  result: CircuitRecommendResponse;
  onAskGuide?: (question: string) => void;
  onRouteStatusChange?: (status: RouteTraceStatus, label: string) => void;
}

export default function CircuitRouteLayer({
  result,
  onAskGuide,
  onRouteStatusChange,
}: CircuitRouteLayerProps) {
  const monuments = result.circuit.monuments;
  const fallbackPolyline = useMemo(
    () =>
      (result.route.polyline ?? []).map(
        ([lat, lng]) => [lat, lng] as [number, number],
      ),
    [result],
  );

  const [routePositions, setRoutePositions] = useState<[number, number][]>([]);

  const routeKey = useMemo(
    () =>
      [
        result.session_id,
        result.route.transport,
        ...monuments.map(
          (m) => `${m.name}:${m.latitude}:${m.longitude}`,
        ),
      ].join("|"),
    [result, monuments],
  );

  useEffect(() => {
    if (monuments.length === 0) {
      setRoutePositions([]);
      onRouteStatusChange?.("idle", "");
      return;
    }

    if (monuments.length === 1) {
      setRoutePositions([[monuments[0].latitude, monuments[0].longitude]]);
      onRouteStatusChange?.("fallback", routeStatusLabel("fallback"));
      return;
    }

    const coordinates = monuments.map((m) => ({
      latitude: m.latitude,
      longitude: m.longitude,
    }));

    let cancelled = false;
    onRouteStatusChange?.("loading", routeStatusLabel("loading"));

    getOsrmRoute(coordinates, result.route.transport)
      .then((positions) => {
        if (cancelled) return;
        setRoutePositions(positions);
        onRouteStatusChange?.("osrm", routeStatusLabel("osrm"));
      })
      .catch(() => {
        if (cancelled) return;
        setRoutePositions(
          fallbackPolyline.length > 0
            ? fallbackPolyline
            : coordinates.map((p) => [p.latitude, p.longitude]),
        );
        onRouteStatusChange?.("fallback", routeStatusLabel("fallback"));
      });

    return () => {
      cancelled = true;
    };
  }, [routeKey, fallbackPolyline, monuments, result, onRouteStatusChange]);

  const markerPositions = monuments.map(
    (m) => [m.latitude, m.longitude] as [number, number],
  );
  const boundsPositions =
    routePositions.length > 0 ? routePositions : markerPositions;

  return (
    <>
      {monuments.map((monument) => (
        <Marker
          key={`${monument.order}-${monument.name}`}
          position={[monument.latitude, monument.longitude]}
          icon={numberedIcon(monument.order)}
        >
          <Popup>
            <strong>{monument.name}</strong>
            <br />
            Visite : {Math.round(monument.visit_duration_min)} min
            <br />
            Prix : {monument.price == null ? "non renseigné" : `${monument.price.toFixed(0)} TND`}
            {monument.arrival_time && monument.departure_time && (
              <>
                <br />
                {monument.arrival_time} → {monument.departure_time}
              </>
            )}
            {onAskGuide && (
              <div className="circuit-popup-actions">
                <button
                  type="button"
                  className="btn-secondary btn-compact"
                  onClick={() => onAskGuide(`Pourquoi visiter ${monument.name} ?`)}
                >
                  Pourquoi visiter ?
                </button>
              </div>
            )}
          </Popup>
        </Marker>
      ))}
      {routePositions.length >= 2 && (
        <Polyline
          positions={routePositions}
          pathOptions={{ color: "#fa7921", weight: 5, opacity: 0.9 }}
        />
      )}
      <CircuitFitBounds positions={boundsPositions} />
    </>
  );
}

function CircuitFitBounds({ positions }: { positions: [number, number][] }) {
  const map = useMap();
  const lastSignature = useRef<string | null>(null);

  useEffect(() => {
    if (positions.length === 0) return;
    const signature = positionsSignature(positions);
    if (signature === lastSignature.current) return;
    lastSignature.current = signature;

    if (positions.length === 1) {
      map.setView(positions[0], 15);
      return;
    }
    map.fitBounds(L.latLngBounds(positions), { padding: [40, 40] });
  }, [map, positions]);

  return null;
}

export function circuitFitPositions(
  result: CircuitRecommendResponse | null,
): [number, number][] {
  if (!result) return [];
  const monuments = result.circuit.monuments;
  if (monuments.length === 0) return [];
  return monuments.map((m) => [m.latitude, m.longitude] as [number, number]);
}
