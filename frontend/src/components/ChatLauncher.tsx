interface ChatLauncherProps {
  open: boolean;
  onToggle: () => void;
}

export default function ChatLauncher({ open, onToggle }: ChatLauncherProps) {
  if (open) return null;

  return (
    <div className="chat-launcher-wrap">
      <span className="chat-launcher-tooltip" aria-hidden="true">
        Guide Dourbia
      </span>
      <button
        type="button"
        className="chat-launcher"
        onClick={onToggle}
        aria-label="Ouvrir le guide historique"
        aria-expanded={open}
      >
        <img src="/dourbia-icon.png" alt="" className="chat-launcher-logo" />
      </button>
    </div>
  );
}
