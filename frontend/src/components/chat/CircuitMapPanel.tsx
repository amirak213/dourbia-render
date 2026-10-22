import { useEffect, useMemo, useRef, useState } from "react";
import { Marker, Popup, Polyline } from "react-leaflet";
import L from "leaflet";
import DourbiaMap from "../map/DourbiaMap";
import CircuitRouteLayer from "../map/CircuitRouteLayer";
import { sendPositionUpdate } from "../../api/position";
import { useWorkspace } from "../../context/WorkspaceContext";
import type { CircuitRecommendResponse } from "../../types/circuit";

const guideIcon = L.divIcon({
  className: "circuit-leaflet-marker",
  html: '<div class="circuit-marker-pin">●</div>',
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

export default function CircuitMapPanel() {
  const { activeCircuit, guideEnabled, openGuideWithQuestion } = useWorkspace();
  console.log("CircuitMapPanel activeCircuit:", activeCircuit);

  const [geoError, setGeoError] = useState<string | null>(null);
  const [currentPosition, setCurrentPosition] = useState<[number, number] | null>(null);
  const [positions, setPositions] = useState<[number, number][]>([]);
  const watchIdRef = useRef<number | null>(null);

  // Relu à chaque rendu : chat-session-id n'existe qu'après la 1re réponse du chat
  const sessionId = window.sessionStorage.getItem("chat-session-id") ?? "";

  // Convertit WizardCircuitSummary → CircuitRecommendResponse pour CircuitRouteLayer
  const previewResult = useMemo<CircuitRecommendResponse | null>(() => {
    if (!activeCircuit || activeCircuit.monuments.length === 0) return null;
    return {
      session_id: sessionId || "wizard-preview",
      circuit: {
        title: activeCircuit.title,
        summary: activeCircuit.summary,
        monuments: activeCircuit.monuments.map((item) => ({
          order: item.order,
          monument_id: undefined,
          name: item.name,
          latitude: item.latitude ?? 36.857,
          longitude: item.longitude ?? 10.33,
          visit_duration_min: item.visit_duration_min,
          price: item.price,
          reason: "Étape du circuit",
        })),
        total_visit_duration_min: activeCircuit.total_duration_min,
        total_travel_duration_min: 0,
        total_duration_min: activeCircuit.total_duration_min,
        total_distance_km: 0,
        total_price: activeCircuit.total_price,
        unknown_price_count: activeCircuit.unknown_price_count,
        budget_max: activeCircuit.budget_max,
        score: 0,
      },
      route: activeCircuit.route ?? { transport: "walking", polyline: [], segments: [] },
      constraints: { budget_ok: true, duration_ok: true, mobility_ok: true },
      explanation: [],
      alternatives: [],
      warnings: [],
      feasible: true,
    };
  }, [activeCircuit, sessionId]);

  // Géolocalisation : s'active uniquement quand guideEnabled est true
  const lastTriggeredMonumentRef = useRef<string | null>(null);
  useEffect(() => {
    if (!guideEnabled || typeof navigator === "undefined" || !navigator.geolocation) {
      return;
    }

    const success = (position: GeolocationPosition) => {
      const nextPoint: [number, number] = [position.coords.latitude, position.coords.longitude];
      setCurrentPosition(nextPoint);
      setPositions((prev) => (prev.length === 0 ? [nextPoint] : [...prev.slice(-9), nextPoint]));
      void sendPositionUpdate({
        session_id: sessionId || undefined,
        user_id: sessionId || undefined,
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        langue: "FR",
      })
        .then((res) => {
          if (res.triggered && res.monument && lastTriggeredMonumentRef.current !== res.monument) {
            lastTriggeredMonumentRef.current = res.monument;
            openGuideWithQuestion(`Parle-moi de ${res.monument}`);
          }
        })
        .catch(() => undefined);
    };

    const error = (err: GeolocationPositionError) => {
      if (err.code === err.PERMISSION_DENIED) {
        setGeoError(
          "L'accès à la position a été refusé. Vous pouvez réactiver la permission dans votre navigateur.",
        );
      } else {
        setGeoError("La géolocalisation est indisponible pour le moment.");
      }
    };

    navigator.geolocation.getCurrentPosition(success, error, {
      enableHighAccuracy: true,
      timeout: 10_000,
    });
    watchIdRef.current = navigator.geolocation.watchPosition(success, error, {
      enableHighAccuracy: true,
      timeout: 15_000,
      maximumAge: 5_000,
    });

    return () => {
      if (watchIdRef.current !== null) {
        navigator.geolocation.clearWatch(watchIdRef.current);
        watchIdRef.current = null;
      }
      lastTriggeredMonumentRef.current = null;
    };
  }, [guideEnabled, sessionId]);

  // Réinitialise les données GPS quand le guide est désactivé
  useEffect(() => {
    if (!guideEnabled) {
      setCurrentPosition(null);
      setPositions([]);
      setGeoError(null);
    }
  }, [guideEnabled]);

  if (!activeCircuit || !previewResult) return null;

  // Centre de la carte : 1er monument du circuit, ou fallback Tunis
  const firstStop = activeCircuit.monuments[0];
  const mapCenter: [number, number] = [
    firstStop?.latitude ?? 36.857,
    firstStop?.longitude ?? 10.33,
  ];

  return (
    <div style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column" }}>
      {guideEnabled && (
        <div
          style={{
            padding: "0.4rem 0.75rem",
            fontSize: "0.85rem",
            background: "var(--color-surface, #1e1e2e)",
            borderBottom: "1px solid var(--color-border, #333)",
            color: "var(--color-accent, #2A7FFF)",
          }}
        >
          📍 Position actuelle · suivi actif
        </div>
      )}
      {geoError && (
        <p className="wizard-warning" role="alert" style={{ margin: "0.5rem 0.75rem" }}>
          {geoError}
        </p>
      )}
      <div style={{ flex: 1, minHeight: 0 }}>
        <DourbiaMap center={mapCenter} zoom={14}>
          {/* Tracé du circuit — toujours visible dès qu'un circuit est actif */}
          <CircuitRouteLayer result={previewResult} />

          {/* Marqueurs GPS — uniquement si le guide est actif */}
          {guideEnabled && currentPosition && (
            <Marker position={currentPosition} icon={guideIcon}>
              <Popup>Vous êtes ici</Popup>
            </Marker>
          )}
          {guideEnabled && positions.length > 1 && (
            <Polyline positions={positions} pathOptions={{ color: "#2A7FFF", weight: 4 }} />
          )}
        </DourbiaMap>
      </div>
    </div>
  );
}
