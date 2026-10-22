import { useState } from "react";
import {
  CIRCUIT_FORM_STEPS,
  DEFAULT_CIRCUIT_FORM,
  EXTRA_MONUMENT_OPTIONS,
  FEATURED_MONUMENT_OPTIONS,
  MOBILITE_LABELS,
  TARIF_LABELS,
  TRANSPORT_LABELS,
} from "../../content/circuitContent";
import { useMonuments } from "../../hooks/useMonuments";
import type { CircuitFormState } from "../../types/circuit";
import { monumentDisplayName } from "../../types/monument";
import CircuitFormStep from "./CircuitFormStep";
import CircuitPreferences from "./CircuitPreferences";

interface CircuitRecommendationFormProps {
  form: CircuitFormState;
  loading: boolean;
  onChange: (form: CircuitFormState) => void;
  onSubmit: () => void;
}

const TOTAL_STEPS = CIRCUIT_FORM_STEPS.length;

function toggleChip(list: string[], value: string): string[] {
  return list.includes(value)
    ? list.filter((item) => item !== value)
    : [...list, value];
}

export default function CircuitRecommendationForm({
  form,
  loading,
  onChange,
  onSubmit,
}: CircuitRecommendationFormProps) {
  const [step, setStep] = useState(1);
  const [showAllMonuments, setShowAllMonuments] = useState(false);
  const { monuments } = useMonuments();

  function update<K extends keyof CircuitFormState>(key: K, value: CircuitFormState[K]) {
    onChange({ ...form, [key]: value });
  }

  const apiMonumentNames = monuments.map((m) => monumentDisplayName(m));
  const fallbackNames = [...FEATURED_MONUMENT_OPTIONS, ...EXTRA_MONUMENT_OPTIONS];
  const allMonumentNames =
    apiMonumentNames.length > 0 ? apiMonumentNames : [...fallbackNames];

  const featuredCount = Math.min(7, allMonumentNames.length);
  const visibleMonuments = showAllMonuments
    ? allMonumentNames
    : allMonumentNames.slice(0, featuredCount);

  const stepTitle = CIRCUIT_FORM_STEPS[step - 1]?.title ?? "";

  function handleNext() {
    if (step < TOTAL_STEPS) {
      setStep((current) => current + 1);
    }
  }

  function handlePrevious() {
    if (step > 1) {
      setStep((current) => current - 1);
    }
  }

  return (
    <form
      className="circuit-form card-panel"
      onSubmit={(event) => {
        event.preventDefault();
        if (step < TOTAL_STEPS) {
          handleNext();
          return;
        }
        onSubmit();
      }}
    >
      <header className="circuit-form-header">
        <h2>Votre circuit sur mesure</h2>
        <p>Quelques informations suffisent pour générer un parcours adapté à Carthage.</p>
      </header>

      <CircuitFormStep step={step} totalSteps={TOTAL_STEPS} title={stepTitle}>
        {step === 1 && (
          <div className="circuit-form-grid circuit-form-grid-compact">
            <label className="circuit-field">
              <span>Type de tarif</span>
              <select
                value={form.type_tarif}
                onChange={(e) =>
                  update("type_tarif", e.target.value as CircuitFormState["type_tarif"])
                }
              >
                {Object.entries(TARIF_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>

            <label className="circuit-field">
              <span>Budget max (TND)</span>
              <input
                type="number"
                min={1}
                step={1}
                required
                value={form.budget_max}
                onChange={(e) => update("budget_max", e.target.value)}
              />
            </label>

            <label className="circuit-field">
              <span>Mobilité</span>
              <select
                value={form.mobilite}
                onChange={(e) =>
                  update("mobilite", e.target.value as CircuitFormState["mobilite"])
                }
              >
                {Object.entries(MOBILITE_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>

            <label className="circuit-field">
              <span>Transport</span>
              <select
                value={form.transport}
                onChange={(e) =>
                  update("transport", e.target.value as CircuitFormState["transport"])
                }
              >
                {Object.entries(TRANSPORT_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {step === 2 && (
          <div className="circuit-form-grid circuit-form-grid-compact">
            <label className="circuit-field">
              <span>Durée (minutes)</span>
              <input
                type="number"
                min={15}
                max={720}
                value={form.duration_minutes}
                onChange={(e) => update("duration_minutes", e.target.value)}
              />
            </label>

            <label className="circuit-field">
              <span>Heure de début</span>
              <input
                type="time"
                value={form.start_time}
                onChange={(e) => update("start_time", e.target.value)}
              />
            </label>

            <label className="circuit-field circuit-field-wide">
              <span>Heure de fin</span>
              <input
                type="time"
                value={form.end_time}
                onChange={(e) => update("end_time", e.target.value)}
              />
            </label>
          </div>
        )}

        {step === 3 && (
          <CircuitPreferences
            form={form}
            onTogglePeriod={(value) => update("epoques", toggleChip(form.epoques, value))}
            onToggleFunction={(value) => update("fonctions", toggleChip(form.fonctions, value))}
          />
        )}

        {step === 4 && (
          <>
            <p className="circuit-section-hint">
              Optionnel : choisissez quelques monuments que vous souhaitez absolument inclure.
            </p>
            <div className="circuit-chips">
              {visibleMonuments.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`circuit-chip${form.must_visit.includes(option) ? " active" : ""}`}
                  onClick={() => update("must_visit", toggleChip(form.must_visit, option))}
                  aria-pressed={form.must_visit.includes(option)}
                >
                  {option}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="circuit-toggle-more"
              onClick={() => setShowAllMonuments((open) => !open)}
            >
              {showAllMonuments ? "Voir moins" : "Voir plus"}
            </button>
          </>
        )}
      </CircuitFormStep>

      <div className="circuit-form-actions">
        <div className="circuit-form-nav">
          {step > 1 && (
            <button
              type="button"
              className="btn-secondary"
              disabled={loading}
              onClick={handlePrevious}
            >
              Précédent
            </button>
          )}
          {step < TOTAL_STEPS ? (
            <button type="submit" className="btn-primary" disabled={loading}>
              Continuer
            </button>
          ) : (
            <button type="submit" className="btn-primary circuit-submit-btn" disabled={loading}>
              {loading ? "Optimisation du circuit…" : "Créer mon circuit"}
            </button>
          )}
        </div>
        <button
          type="button"
          className="btn-secondary btn-compact circuit-reset-btn"
          disabled={loading}
          onClick={() => {
            onChange({
              ...DEFAULT_CIRCUIT_FORM,
              must_visit: [...DEFAULT_CIRCUIT_FORM.must_visit],
            });
            setStep(1);
          }}
        >
          Réinitialiser
        </button>
      </div>
    </form>
  );
}
