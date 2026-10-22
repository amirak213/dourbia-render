import type { CircuitRecommendResponse } from "../../types/circuit";
import Badge from "../ui/Badge";
import CircuitSummaryCards from "./CircuitSummaryCards";

interface CircuitResultPanelProps {
  result: CircuitRecommendResponse;
}

export default function CircuitResultPanel({ result }: CircuitResultPanelProps) {
  const { circuit, constraints, warnings, feasible } = result;

  return (
    <section className="circuit-result card-panel" aria-live="polite">
      <div className="circuit-result-header">
        <div>
          <h2>{circuit.title}</h2>
          <p className="circuit-result-summary">{circuit.summary}</p>
        </div>
        <Badge variant={feasible ? "default" : "warn"}>
          {feasible ? "Circuit réalisable" : "Contraintes partielles"}
        </Badge>
      </div>

      <CircuitSummaryCards circuit={circuit} constraints={constraints} />

      {warnings.length > 0 && (
        <div className="circuit-warnings">
          <h3>Avertissements</h3>
          <ul>
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
