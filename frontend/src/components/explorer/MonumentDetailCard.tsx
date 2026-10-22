import { FUNCTION_LABELS } from "../../content/circuitContent";
import type { MonumentSummary } from "../../types/monument";
import { monumentDisplayName } from "../../types/monument";

interface MonumentDetailCardProps {
  monument: MonumentSummary;
  compact?: boolean;
  isMustVisit?: boolean;
  onViewOnMap?: () => void;
  onAskGuide: () => void;
  onAddToCircuit: () => void;
}

function formatMeta(monument: MonumentSummary): string {
  const parts: string[] = [];
  if (monument.dominant_period) parts.push(monument.dominant_period);
  if (monument.visit_duration_min != null) {
    parts.push(`${Math.round(monument.visit_duration_min)} min`);
  }
  if (monument.function) {
    const label =
      FUNCTION_LABELS[monument.function as keyof typeof FUNCTION_LABELS] ??
      monument.function;
    parts.push(label);
  }
  return parts.join(" · ");
}

export default function MonumentDetailCard({
  monument,
  compact = false,
  isMustVisit = false,
  onViewOnMap,
  onAskGuide,
  onAddToCircuit,
}: MonumentDetailCardProps) {
  const name = monumentDisplayName(monument);

  return (
    <div className={`monument-detail-card${compact ? " monument-detail-compact" : ""}`}>
      <h3>{name}</h3>
      <p className="monument-detail-meta">{formatMeta(monument)}</p>
      <div className="monument-detail-actions">
        {!compact && onViewOnMap && (
          <button type="button" className="btn-mini" onClick={onViewOnMap}>
            En savoir plus
          </button>
        )}
        <button type="button" className="btn-mini btn-mini-primary" onClick={onAskGuide}>
          Demander au guide
        </button>
        <button
          type="button"
          className={`btn-mini${isMustVisit ? " btn-mini-active" : ""}`}
          onClick={onAddToCircuit}
          aria-pressed={isMustVisit}
        >
          {isMustVisit ? "✓ Circuit" : "+ Circuit"}
        </button>
      </div>
    </div>
  );
}
