import type { SiteView } from "../../content/siteContent";
import { useWorkspace } from "../../context/WorkspaceContext";
import Button from "../ui/Button";

interface CircuitShortcutPanelProps {
  onNavigate: (view: SiteView) => void;
}

export default function CircuitShortcutPanel({ onNavigate }: CircuitShortcutPanelProps) {
  const { mustVisitMonuments, toggleMustVisit } = useWorkspace();
  const hasWishes = mustVisitMonuments.length > 0;

  return (
    <div className="circuit-shortcut-panel">
      <h3>Monuments souhaités</h3>
      {!hasWishes ? (
        <p className="circuit-shortcut-empty">
          Ajoutez des monuments depuis la carte ou l&apos;explorateur, puis générez
          votre circuit personnalisé.
        </p>
      ) : (
        <ul className="circuit-shortcut-list">
          {mustVisitMonuments.map((name) => (
            <li key={name} className="circuit-shortcut-item">
              <span className="circuit-shortcut-name">{name}</span>
              <button
                type="button"
                className="circuit-shortcut-remove"
                onClick={() => toggleMustVisit(name)}
                aria-label={`Retirer ${name} de mes souhaits`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="circuit-shortcut-actions">
        <Button variant="secondary" onClick={() => onNavigate("circuit")}>
          Modifier mes préférences
        </Button>
        <Button variant="primary" onClick={() => onNavigate("circuit")}>
          Créer mon circuit
        </Button>
      </div>
    </div>
  );
}
