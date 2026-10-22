interface LoadingStateProps {
  message: string;
}

export default function LoadingState({ message }: LoadingStateProps) {
  return (
    <div className="ui-loading-state card-panel" role="status" aria-live="polite">
      <span className="ui-loading-spinner" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}
