import { FUNCTION_LABELS, FUNCTION_OPTIONS, PERIOD_OPTIONS } from "../../content/circuitContent";
import type { CircuitFormState } from "../../types/circuit";

interface CircuitPreferencesProps {
  form: CircuitFormState;
  onTogglePeriod: (value: string) => void;
  onToggleFunction: (value: string) => void;
}

function ChipRow({
  options,
  labels,
  selected,
  onToggle,
}: {
  options: readonly string[];
  labels?: Record<string, string>;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <div className="circuit-chips">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          className={`circuit-chip${selected.includes(option) ? " active" : ""}`}
          onClick={() => onToggle(option)}
          aria-pressed={selected.includes(option)}
        >
          {labels?.[option] ?? option}
        </button>
      ))}
    </div>
  );
}

export default function CircuitPreferences({
  form,
  onTogglePeriod,
  onToggleFunction,
}: CircuitPreferencesProps) {
  return (
    <>
      <div className="circuit-chip-block">
        <span className="circuit-chip-label">Époques historiques</span>
        <ChipRow
          options={PERIOD_OPTIONS}
          selected={form.epoques}
          onToggle={onTogglePeriod}
        />
      </div>
      <div className="circuit-chip-block">
        <span className="circuit-chip-label">Types de sites</span>
        <ChipRow
          options={FUNCTION_OPTIONS}
          labels={FUNCTION_LABELS}
          selected={form.fonctions}
          onToggle={onToggleFunction}
        />
      </div>
    </>
  );
}
