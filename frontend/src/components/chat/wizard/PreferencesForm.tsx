import { useState } from "react";
import type { WizardOption } from "../../../types";
import Button from "../../ui/Button";

interface PreferencesFormProps {
  options: WizardOption[];
  interactive: boolean;
  onSubmit: (value: { epoques: string[]; fonctions: string[] }, label: string) => void;
}

export default function PreferencesForm({ options, interactive, onSubmit }: PreferencesFormProps) {
  const [selectedEpoques, setSelectedEpoques] = useState<Set<string>>(new Set());
  const [selectedFonctions, setSelectedFonctions] = useState<Set<string>>(new Set());

  const epoques = options.filter(o => o.meta?.type === "epoque");
  const fonctions = options.filter(o => o.meta?.type === "fonction");

  function toggleEpoque(value: string) {
    if (!interactive) return;
    const next = new Set(selectedEpoques);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setSelectedEpoques(next);
  }

  function toggleFonction(value: string) {
    if (!interactive) return;
    const next = new Set(selectedFonctions);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setSelectedFonctions(next);
  }

  function handleSubmit() {
    const ep = Array.from(selectedEpoques);
    const fn = Array.from(selectedFonctions);
    const count = ep.length + fn.length;
    onSubmit(
      { epoques: ep, fonctions: fn },
      count === 0 ? "Pas de préférence" : `${count} préférence(s)`
    );
  }

  return (
    <div className={`wizard-form${interactive ? "" : " wizard-disabled"}`}>
      <div className="wizard-form-row">
        <div style={{ flex: 1 }}>
          <h4 style={{ margin: "0 0 8px 0", fontSize: "0.9em", color: "var(--text-secondary)" }}>Époques</h4>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
            {epoques.map(opt => (
              <button
                type="button"
                key={opt.value}
                className={`wizard-chip ${selectedEpoques.has(opt.value) ? "selected" : ""}`}
                onClick={() => toggleEpoque(opt.value)}
                disabled={!interactive}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        
        <div style={{ flex: 1 }}>
          <h4 style={{ margin: "0 0 8px 0", fontSize: "0.9em", color: "var(--text-secondary)" }}>Types</h4>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
            {fonctions.map(opt => (
              <button
                type="button"
                key={opt.value}
                className={`wizard-chip ${selectedFonctions.has(opt.value) ? "selected" : ""}`}
                onClick={() => toggleFonction(opt.value)}
                disabled={!interactive}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      
      {interactive && (
        <Button variant="primary" compact onClick={handleSubmit}>
          {selectedEpoques.size === 0 && selectedFonctions.size === 0 ? "Passer" : "Valider"}
        </Button>
      )}
    </div>
  );
}
