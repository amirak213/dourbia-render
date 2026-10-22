import { FUNCTION_LABELS } from "../../content/circuitContent";
import type { MonumentSummary } from "../../types/monument";
import { monumentDisplayName } from "../../types/monument";
import MonumentThumb from "./MonumentThumb";

interface MonumentCardProps {
  monument: MonumentSummary;
  selected?: boolean;
  isMustVisit?: boolean;
  onViewOnMap: () => void;
  onAskGuide: () => void;
  onAddToCircuit: () => void;
}

function formatMeta(monument: MonumentSummary): string {
  const parts: string[] = [];
  if (monument.dominant_period) parts.push(monument.dominant_period);
  if (monument.function) {
    const label =
      FUNCTION_LABELS[monument.function as keyof typeof FUNCTION_LABELS] ??
      monument.function;
    parts.push(label);
  }
  if (monument.visit_duration_min != null) {
    parts.push(`${Math.round(monument.visit_duration_min)} min`);
  }
  return parts.join(" · ");
}

export default function MonumentCard({
  monument,
  selected = false,
  isMustVisit = false,
  onViewOnMap,
  onAskGuide,
  onAddToCircuit,
}: MonumentCardProps) {
  const name = monumentDisplayName(monument);

  return (
    <article className={`monument-card${selected ? " selected" : ""}`}>
      <div className="monument-card-main">
        <MonumentThumb monument={monument} />
        <div className="monument-card-info">
          <h3 className="monument-card-title">{name}</h3>
          <p className="monument-card-meta">{formatMeta(monument)}</p>
        </div>
      </div>
      <div className="monument-card-actions">
        <button type="button" className="btn-mini btn-mini-primary" onClick={onViewOnMap}>
          Carte
        </button>
        <button type="button" className="btn-mini" onClick={onAskGuide}>
          Guide
        </button>
        <button
          type="button"
          className={`btn-mini${isMustVisit ? " btn-mini-active" : ""}`}
          onClick={onAddToCircuit}
          aria-pressed={isMustVisit}
          title={isMustVisit ? "Retirer du circuit" : "Ajouter aux monuments souhaités"}
        >
          {isMustVisit ? "✓ Circuit" : "+ Circuit"}
        </button>
      </div>
    </article>
  );
}
