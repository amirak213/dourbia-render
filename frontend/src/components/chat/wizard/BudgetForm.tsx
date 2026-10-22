import { useState } from "react";
import type { WizardOption } from "../../../types";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";

interface BudgetFormProps {
  options: WizardOption[];
  interactive: boolean;
  onSubmit: (value: { type: string; amount: number }, label: string) => void;
}

export default function BudgetForm({ options, interactive, onSubmit }: BudgetFormProps) {
  const [type, setType] = useState<string | null>(null);
  const [amount, setAmount] = useState("");

  const amountNumber = Number(amount);
  const canSubmit = Boolean(type) && amount.trim() !== "" && amountNumber > 0;

  function handleSubmit() {
    if (!type || !canSubmit) return;
    const typeLabel = options.find((option) => option.value === type)?.label ?? type;
    onSubmit({ type, amount: amountNumber }, `${typeLabel} · ${amountNumber} DT`);
  }

  return (
    <div className={`wizard-form${interactive ? "" : " wizard-disabled"}`}>
      <div className="wizard-chip-row" role="group">
        {options.map((option) => (
          <Chip
            key={option.value}
            label={option.label}
            selected={type === option.value}
            onClick={interactive ? () => setType(option.value) : undefined}
          />
        ))}
      </div>
      <div className="wizard-form-row">
        <input
          type="number"
          min={1}
          inputMode="decimal"
          className="wizard-input"
          placeholder="Budget par personne (DT)"
          value={amount}
          disabled={!interactive}
          onChange={(event) => setAmount(event.target.value)}
          aria-label="Budget par personne en dinars"
        />
        {interactive && (
          <Button variant="primary" compact onClick={handleSubmit} disabled={!canSubmit}>
            Continuer
          </Button>
        )}
      </div>
    </div>
  );
}
