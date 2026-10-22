import type { WizardOption } from "../../../types";
import Chip from "../../ui/Chip";

interface SingleSelectCardsProps {
  options: WizardOption[];
  interactive: boolean;
  onSelect: (option: WizardOption) => void;
}

export default function SingleSelectCards({
  options,
  interactive,
  onSelect,
}: SingleSelectCardsProps) {
  return (
    <div
      className={`wizard-chip-row${interactive ? "" : " wizard-disabled"}`}
      role="group"
    >
      {options.map((option) => (
        <Chip
          key={option.value}
          label={option.label}
          onClick={interactive ? () => onSelect(option) : undefined}
        />
      ))}
    </div>
  );
}
