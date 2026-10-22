interface ChipProps {
  label: string;
  selected?: boolean;
  onClick?: () => void;
}

export default function Chip({ label, selected = false, onClick }: ChipProps) {
  return (
    <button
      type="button"
      className={`ui-chip${selected ? " ui-chip-selected" : ""}`}
      onClick={onClick}
      aria-pressed={selected}
    >
      {label}
    </button>
  );
}
