interface CircuitEmptyStateProps {
  message?: string;
}

export default function CircuitEmptyState({
  message = "Renseignez vos préférences pour générer un circuit personnalisé à Carthage.",
}: CircuitEmptyStateProps) {
  return (
    <div className="circuit-status card-panel circuit-status-empty" role="status">
      {message}
    </div>
  );
}
