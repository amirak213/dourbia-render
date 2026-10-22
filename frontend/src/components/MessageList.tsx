import { useEffect, useRef } from "react";
import type { ChatSession, WizardAction } from "../types";
import MessageBubble from "./MessageBubble";

const SUGGESTION_CHIPS: { label: string; message: string }[] = [
  { label: "Thermes d'Antonin", message: "Parle-moi des Thermes d'Antonin." },
  { label: "Tophet de Carthage", message: "Qu'est-ce que le Tophet de Carthage ?" },
  { label: "Créer un circuit", message: "Je veux créer un circuit de visite." },
  { label: "Météo aujourd'hui", message: "Quel temps fait-il aujourd'hui à Carthage ?" },

];

interface MessageListProps {
  chat: ChatSession | null;
  loading: boolean;
  error: string | null;
  loadingMessage?: string;
  onSuggestedAction: (text: string) => void;
  onWizardAnswer?: (action: WizardAction, label: string) => void;
}

export default function MessageList({
  chat,
  loading,
  error,
  loadingMessage = "Recherche dans les sources historiques…",
  onSuggestedAction,
  onWizardAnswer,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat?.messages.length, loading, error]);

  return (
    <main
      className="messages chat-widget-messages chat-scroll"
      ref={containerRef}
      aria-live="polite"
    >
      {!chat || chat.messages.length === 0 ? (
        <div className="welcome welcome-compact">
          <img src="/dourbia-icon.png" alt="" className="welcome-icon" />
          <h3 className="welcome-title">Bienvenue sur Dourbia 👋</h3>
          <p className="welcome-tagline">
            Je suis votre guide intelligent pour explorer Carthage et La Marsa.
            Je peux vous renseigner sur l'histoire des monuments, vous créer un
            circuit de visite sur mesure selon votre budget et vos envies, vous
            donner la météo du jour, ou encore vous guider en temps réel une
            fois sur place.
          </p>
          <div className="welcome-chips">
            {SUGGESTION_CHIPS.map((chip) => (
              <button
                key={chip.label}
                type="button"
                className="action-chip welcome-chip"
                onClick={() => onSuggestedAction(chip.message)}
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        chat.messages.map((message, index) => (
          <MessageBubble
            key={message.id}
            message={message}
            onSuggestedActionClick={onSuggestedAction}
            isLatest={index === chat.messages.length - 1}
            onWizardAnswer={onWizardAnswer}
          />
        ))
      )}
      {loading && (
        <div className="message-row assistant loading-row">
          <img src="/dourbia-icon.png" alt="" className="message-avatar-img" />
          <div className="message-body loading-bubble">
            <p className="loading-text">{loadingMessage}</p>
            <div className="typing-indicator" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          </div>
        </div>
      )}
      {error && (
        <div className="message-row assistant error-row" role="alert">
          <div className="message-body error-bubble">{error}</div>
        </div>
      )}
      <div ref={bottomRef} />
    </main>
  );
}
