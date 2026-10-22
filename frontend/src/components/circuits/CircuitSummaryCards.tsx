import type { CircuitConstraintsStatus, CircuitSummary } from "../../types/circuit";

interface CircuitSummaryCardsProps {
  circuit: CircuitSummary;
  constraints: CircuitConstraintsStatus;
}

function formatMinutes(value: number): string {
  return `${Math.round(value)} min`;
}

export default function CircuitSummaryCards({
  circuit,
  constraints,
}: CircuitSummaryCardsProps) {
  const monumentCount = circuit.monuments?.length ?? 0;

  return (
    <>
      <div className="circuit-summary-cards">
        <article className="circuit-stat-card">
          <span className="circuit-stat-label">Durée</span>
          <strong>{formatMinutes(circuit.total_duration_min)}</strong>
          <small>
            Visite {formatMinutes(circuit.total_visit_duration_min)} · Trajet{" "}
            {formatMinutes(circuit.total_travel_duration_min)}
          </small>
        </article>
        <article className="circuit-stat-card">
          <span className="circuit-stat-label">Distance</span>
          <strong>{circuit.total_distance_km.toFixed(1)} km</strong>
        </article>
        <article className="circuit-stat-card">
          <span className="circuit-stat-label">Budget total</span>
          <strong>{circuit.total_price.toFixed(0)} TND</strong>
        </article>
        <article className="circuit-stat-card">
          <span className="circuit-stat-label">Monuments</span>
          <strong>{monumentCount}</strong>
        </article>
      </div>

      <div className="circuit-constraint-status" role="list">
        <span
          className={`circuit-constraint-chip${constraints.budget_ok ? " ok" : " warn"}`}
          role="listitem"
        >
          {constraints.budget_ok ? "✓ Budget respecté" : "⚠ Budget dépassé"}
        </span>
        <span
          className={`circuit-constraint-chip${constraints.duration_ok ? " ok" : " warn"}`}
          role="listitem"
        >
          {constraints.duration_ok ? "✓ Durée respectée" : "⚠ Durée dépassée"}
        </span>
        <span
          className={`circuit-constraint-chip${constraints.mobility_ok ? " ok" : " warn"}`}
          role="listitem"
        >
          {constraints.mobility_ok ? "✓ Mobilité compatible" : "⚠ Mobilité à vérifier"}
        </span>
      </div>
    </>
  );
}
