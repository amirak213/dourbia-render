import { useEffect, useMemo, useState } from "react";
import {
  DEFAULT_CIRCUIT_FORM,
  FUNCTION_LABELS,
  MOBILITE_LABELS,
  TARIF_LABELS,
  TRANSPORT_LABELS,
} from "../../content/circuitContent";
import { useWorkspace } from "../../context/WorkspaceContext";
import { buildCircuitPayload, recommendCircuit } from "../../services/circuitApi";
import type { CircuitFormState, CircuitRecommendResponse } from "../../types/circuit";
import LoadingState from "../ui/LoadingState";
import CircuitEmptyState from "./CircuitEmptyState";
import CircuitMap from "./CircuitMap";
import CircuitRecommendationForm from "./CircuitRecommendationForm";
import CircuitResultPanel from "./CircuitResultPanel";
import CircuitTimeline from "./CircuitTimeline";

function createSessionId(): string {
  return `circuit_${Date.now()}`;
}

function CircuitPreviewPanel({ form }: { form: CircuitFormState }) {
  const profil = [
    TARIF_LABELS[form.type_tarif] ?? form.type_tarif,
    TRANSPORT_LABELS[form.transport] ?? form.transport,
    `Mobilité ${MOBILITE_LABELS[form.mobilite] ?? form.mobilite}`,
  ].join(" · ");

  const preferences = [
    ...form.epoques,
    ...form.fonctions.map((f) => FUNCTION_LABELS[f as keyof typeof FUNCTION_LABELS] ?? f),
  ].join(" · ");

  return (
    <aside className="circuit-preview-panel" aria-label="Aperçu de vos préférences">
      <h3>Aperçu</h3>
      <dl className="circuit-preview-groups">
        <div>
          <dt>Profil</dt>
          <dd>{profil}</dd>
        </div>
        <div>
          <dt>Temps</dt>
          <dd>
            {form.start_time} → {form.end_time} · {form.duration_minutes || "—"} min
          </dd>
        </div>
        {preferences && (
          <div>
            <dt>Préférences</dt>
            <dd>{preferences}</dd>
          </div>
        )}
        <div>
          <dt>Monuments souhaités</dt>
          <dd>{form.must_visit.length}</dd>
        </div>
      </dl>
    </aside>
  );
}

interface CircuitPlannerPageProps {
  onAskGuide?: (question: string) => void;
}

export default function CircuitPlannerPage({ onAskGuide }: CircuitPlannerPageProps) {
  const { mustVisitMonuments } = useWorkspace();
  const [form, setForm] = useState<CircuitFormState>({
    ...DEFAULT_CIRCUIT_FORM,
    must_visit: [...DEFAULT_CIRCUIT_FORM.must_visit],
  });
  const [result, setResult] = useState<CircuitRecommendResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useMemo(() => createSessionId(), []);

  useEffect(() => {
    if (mustVisitMonuments.length > 0) {
      setForm((current) => ({
        ...current,
        must_visit: [...new Set([...current.must_visit, ...mustVisitMonuments])],
      }));
    }
  }, [mustVisitMonuments]);

  async function handleSubmit() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const payload = buildCircuitPayload(form, sessionId);
      const response = await recommendCircuit(payload);
      setResult(response);
    } catch (submitError) {
      setResult(null);
      setError(
        submitError instanceof Error
          ? submitError.message
          : "Impossible de générer un circuit avec ces contraintes. Essayez d'augmenter la durée ou le budget.",
      );
    } finally {
      setLoading(false);
    }
  }

  const hasResult = Boolean(result && !loading);

  return (
    <section className="page-section circuit-planner-page content-panel">
      <header className="page-header">
        <h1>Créer un circuit</h1>
        <p>
          Générez un itinéraire optimisé à Carthage selon votre budget, votre mobilité et vos
          préférences historiques.
        </p>
      </header>

      <div className={`circuit-planner-layout${hasResult ? " has-result" : ""}`}>
        {!hasResult && (
          <aside className="circuit-planner-form-column">
            <CircuitRecommendationForm
              form={form}
              loading={loading}
              onChange={setForm}
              onSubmit={handleSubmit}
            />
          </aside>
        )}

        <div className="circuit-planner-main-column">
          {!hasResult && !loading && <CircuitPreviewPanel form={form} />}
          {loading && <LoadingState message="Optimisation de votre circuit…" />}

          {!loading && error && (
            <div className="circuit-status card-panel circuit-status-error" role="alert">
              {error}
            </div>
          )}

          {!loading && !error && !result && <CircuitEmptyState />}

          {hasResult && result && (
            <div className="circuit-results-layout">
              <div className="circuit-result-actions">
                <button
                  type="button"
                  className="btn-secondary btn-compact"
                  onClick={() => {
                    setResult(null);
                    setError(null);
                  }}
                >
                  Modifier mes préférences
                </button>
              </div>
              <CircuitResultPanel result={result} />
              <div className="circuit-results-map-timeline">
                <CircuitMap result={result} onAskGuide={onAskGuide} />
                <CircuitTimeline monuments={result.circuit.monuments} onAskGuide={onAskGuide} />
              </div>
              {result.explanation.length > 0 && (
                <section className="circuit-explanation card-panel">
                  <h3>Explication</h3>
                  <ul>
                    {result.explanation.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )}

          {!hasResult && !loading && <CircuitMap result={null} />}
        </div>
      </div>
    </section>
  );
}
