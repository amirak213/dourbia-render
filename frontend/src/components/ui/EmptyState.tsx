interface EmptyStateProps {
  message: string;
  error?: boolean;
}

export default function EmptyState({ message, error = false }: EmptyStateProps) {
  return (
    <div
      className={`ui-empty-state card-panel${error ? " ui-empty-state-error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {message}
    </div>
  );
}
