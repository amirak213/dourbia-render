import type { RecommendedMonument } from "../../types/circuit";

interface CircuitTimelineProps {
  monuments: RecommendedMonument[];
  onAskGuide?: (question: string) => void;
}

export default function CircuitTimeline({ monuments, onAskGuide }: CircuitTimelineProps) {
  if (monuments.length === 0) {
    return null;
  }

  return (
    <section className="circuit-timeline card-panel">
      <h2>Itinéraire détaillé</h2>
      <ol className="circuit-timeline-list">
        {monuments.map((monument) => (
          <li key={`${monument.order}-${monument.name}`} className="circuit-timeline-item">
            <div className="circuit-timeline-marker" aria-hidden="true">
              {monument.order}
            </div>
            <div className="circuit-timeline-content">
              <h3>{monument.name}</h3>
              <div className="circuit-timeline-meta">
                {monument.arrival_time && monument.departure_time && (
                  <span>
                    {monument.arrival_time} → {monument.departure_time}
                  </span>
                )}
                <span>
                  {Math.round(monument.visit_duration_min)} min · {monument.price == null ? "Tarif non renseigné" : `${monument.price.toFixed(0)} DT`}
                </span>
              </div>
              {monument.reason && (
                <p className="circuit-timeline-reason">&ldquo;{monument.reason}&rdquo;</p>
              )}
              {onAskGuide && (
                <button
                  type="button"
                  className="btn-secondary btn-compact circuit-timeline-guide-btn"
                  onClick={() => onAskGuide(`Pourquoi visiter ${monument.name} ?`)}
                >
                  Pourquoi visiter ce monument ?
                </button>
              )}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
