import { useEffect } from "react";
import type { WizardOption, WizardCircuitSummary } from "../../../types";
import Button from "../../ui/Button";
import CircuitSummaryCard from "./CircuitSummaryCard";
import { useWorkspace } from "../../../context/WorkspaceContext";

interface ConfirmCardProps {
  options: WizardOption[];
  budgetOk?: boolean | null;
  budgetWarning?: string | null;
  circuit?: WizardCircuitSummary | null;
  interactive: boolean;
  onSelect: (option: WizardOption) => void;
}


export default function ConfirmCard({
  options,
  budgetOk,
  budgetWarning,
  circuit,
  interactive,
  onSelect,
}: ConfirmCardProps) {
  const { setActiveCircuit, setGuideEnabled } = useWorkspace();


  useEffect(() => {
    if (circuit) {
      setActiveCircuit(circuit);
    }
  }, [circuit, setActiveCircuit]);

  async function handleSelect(option: WizardOption) {
    if (!interactive) return;

    if (option.value === "yes") {
      const response = await onSelect(option);
      if (response === undefined) {
        setGuideEnabled(true);
      }
    } else {
      setGuideEnabled(false);
      await onSelect(option);
    }
  }


  return (
    <div className={`wizard-form${interactive ? "" : " wizard-disabled"}`}>
      {circuit && <CircuitSummaryCard circuit={circuit} />}
      {budgetOk === false && budgetWarning && (
        <p className="wizard-warning" role="alert">
          ⚠️ {budgetWarning}
        </p>
      )}
      <div className="wizard-chip-row" role="group">
        {options.map((option) => (
          <Button
            key={option.value}
            variant={option.value === "confirm_circuit" ? "primary" : "secondary"}
            compact
            disabled={!interactive}
            onClick={interactive ? () => handleSelect(option) : undefined}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
