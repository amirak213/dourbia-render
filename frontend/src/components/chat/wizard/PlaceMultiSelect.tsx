import { useState } from "react";
import type { WizardOption } from "../../../types";
import Chip from "../../ui/Chip";
import Button from "../../ui/Button";

interface PlaceMultiSelectProps {
  options: WizardOption[];
  hasMore: boolean;
  interactive: boolean;
  onSubmit: (selected: WizardOption[]) => void;
  onLoadMore?: () => void;
}

export default function PlaceMultiSelect({
  options,
  hasMore,
  interactive,
  onSubmit,
  onLoadMore,
}: PlaceMultiSelectProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  function toggle(value: string) {
    if (!interactive) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(value)) {
        next.delete(value);
      } else {
        next.add(value);
      }
      return next;
    });
  }

  function handleSubmit() {
    const chosen = options.filter((option) => selected.has(option.value));
    onSubmit(chosen);
  }

  return (
    <div className={`wizard-multi-select${interactive ? "" : " wizard-disabled"}`}>
      <div className="wizard-chip-row" role="group">
        {options.map((option) => (
          <Chip
            key={option.value}
            label={option.label}
            selected={selected.has(option.value)}
            onClick={() => toggle(option.value)}
          />
        ))}
      </div>
      {hasMore && (
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
          <p className="wizard-hint">D'autres lieux populaires existent — vous pouvez en afficher davantage.</p>
          {interactive && onLoadMore && (
            <Button variant="secondary" compact onClick={onLoadMore}>
              Voir plus
            </Button>
          )}
        </div>
      )}
      {interactive && (
        <Button
          variant="primary"
          compact
          onClick={handleSubmit}
          disabled={selected.size === 0}
        >
          Valider ma sélection ({selected.size})
        </Button>
      )}
    </div>
  );
}
