import { useState } from "react";
import type { WizardOption } from "../../../types";
import Button from "../../ui/Button";
import Chip from "../../ui/Chip";

interface MobilityFormProps {
  options: WizardOption[];
  interactive: boolean;
  onSubmit: (value: { transport: string; mobilite: string }, label: string) => void;
}

export default function MobilityForm({ options, interactive, onSubmit }: MobilityFormProps) {
  const [transport, setTransport] = useState("");
  const [mobilite, setMobilite] = useState("");

  const transports = options.filter((option) => option.meta?.type === "transport");
  const mobilites = options.filter((option) => option.meta?.type === "mobilite");
  const canSubmit = Boolean(transport) && Boolean(mobilite);

  function handleSubmit() {
    if (!interactive || !canSubmit) return;
    const transportLabel = transports.find((option) => option.value === transport)?.label ?? transport;
    const mobiliteLabel = mobilites.find((option) => option.value === mobilite)?.label ?? mobilite;
    onSubmit({ transport, mobilite }, `${transportLabel} · ${mobiliteLabel}`);
  }

  return (
    <div className={`wizard-form${interactive ? "" : " wizard-disabled"}`}>
      <div className="wizard-form-row">
        <div style={{ flex: 1 }}>
          <h4 style={{ margin: "0 0 8px 0", fontSize: "0.9em", color: "var(--text-secondary)" }}>
            Transport
          </h4>
          <div className="wizard-chip-row" role="group" aria-label="Transport">
            {transports.map((option) => (
              <Chip
                key={option.value}
                label={option.label}
                selected={transport === option.value}
                onClick={interactive ? () => setTransport(option.value) : undefined}
              />
            ))}
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <h4 style={{ margin: "0 0 8px 0", fontSize: "0.9em", color: "var(--text-secondary)" }}>
            Mobilité
          </h4>
          <div className="wizard-chip-row" role="group" aria-label="Mobilité">
            {mobilites.map((option) => (
              <Chip
                key={option.value}
                label={option.label}
                selected={mobilite === option.value}
                onClick={interactive ? () => setMobilite(option.value) : undefined}
              />
            ))}
          </div>
        </div>
      </div>
      {interactive && (
        <Button variant="primary" compact onClick={handleSubmit} disabled={!canSubmit}>
          Valider
        </Button>
      )}
    </div>
  );
}