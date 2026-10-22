import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { sendChatMessage } from "../../api/chat";
import { useWorkspace } from "../../context/WorkspaceContext";
import type { ChatSession, SourceRef, WizardAction } from "../../types";
import { monumentDisplayName } from "../../types/monument";
import MessageList from "../MessageList";
import SessionList from "../SessionList";

interface ChatCoreProps {
  chat: ChatSession | null;
  chats: ChatSession[];
  activeChatId: string | null;
  onNewChat: () => void;
  onSelectChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onEnsureChat: () => string;
  onAppendMessage: (
    chatId: string,
    message: {
      role: "user" | "assistant";
      content: string;
      sources?: ChatSession["messages"][number]["sources"];
      memory?: ChatSession["messages"][number]["memory"];
      actions?: string[];
      wizard?: ChatSession["messages"][number]["wizard"];
      packs?: ChatSession["messages"][number]["packs"];
      elapsedMs?: number;
      latencyMs?: number;
      latencyDebug?: ChatSession["messages"][number]["latencyDebug"];
    },
  ) => void;
  onSourcesReceived?: (sources: SourceRef[]) => void;
  showSessionsToggle?: boolean;
  autoFocus?: boolean;
}

export default function ChatCore({
  chat,
  chats,
  activeChatId,
  onNewChat,
  onSelectChat,
  onDeleteChat,
  onEnsureChat,
  onAppendMessage,
  onSourcesReceived,
  showSessionsToggle = true,
  autoFocus = true,
}: ChatCoreProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const { selectedMonument, pendingGuideQuestion, setPendingGuideQuestion } = useWorkspace();

  const dispatchToBackend = useCallback(
    async (
      userDisplayText: string,
      message: string,
      action?: WizardAction,
    ) => {
      if (loading) return;

      const chatId = chat?.id ?? onEnsureChat();
      setInput("");
      setError(null);
      setLoading(true);
      onAppendMessage(chatId, { role: "user", content: userDisplayText });

      try {
        const data = await sendChatMessage(chatId, message, "auto", action);
        window.sessionStorage.setItem("chat-session-id", data.session_id);
        onAppendMessage(chatId, {
          role: "assistant",
          content: data.answer,
          sources: data.sources,
          memory: data.memory_context,
          actions: data.suggested_actions,
          wizard: data.wizard_ui ?? undefined,
          packs: data.packs ?? undefined,
          elapsedMs: data.clientElapsedMs,
          latencyMs: data.latency_ms ?? undefined,
          latencyDebug: data.latency_debug ?? undefined,
        });
        if (data.sources.length > 0) {
          onSourcesReceived?.(data.sources);
        }
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Impossible d'obtenir une réponse pour le moment. Réessayez.",
        );
      } finally {
        setLoading(false);
      }
    },
    [
      chat,
      onEnsureChat,
      setInput,
      setError,
      setLoading,
      onAppendMessage,
      onSourcesReceived,
      loading,
    ],
  );

  const sendUserMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      await dispatchToBackend(trimmed, trimmed);
    },
    [dispatchToBackend],
  );

  useEffect(() => {
    if (!pendingGuideQuestion || loading) return;
    const question = pendingGuideQuestion;
    setPendingGuideQuestion(null);
    void sendUserMessage(question);
  }, [pendingGuideQuestion, loading, setPendingGuideQuestion, sendUserMessage]);

  useEffect(() => {
    if (autoFocus) {
      inputRef.current?.focus();
    }
  }, [autoFocus]);

  async function sendWizardAction(action: WizardAction, label: string) {
    // message vide : le backend accepte action seule (voir ChatRequest côté Dourbia)
    await dispatchToBackend(label, "", action);
  }

  function handleSuggestedAction(action: string) {
    void sendUserMessage(action);
  }

  async function submitMessage() {
    await sendUserMessage(input);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void submitMessage();
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitMessage();
    }
  }

  function handleNewChat() {
    onNewChat();
    setSessionsOpen(false);
    setError(null);
    inputRef.current?.focus();
  }

  return (
    <div className="chat-core">
      <div className="chat-core-toolbar">
        <button type="button" className="chat-widget-new" onClick={handleNewChat}>
          + Nouveau chat
        </button>
        {showSessionsToggle && chats.length > 0 && (
          <button
            type="button"
            className="chat-widget-sessions-toggle"
            onClick={() => setSessionsOpen((value) => !value)}
            aria-expanded={sessionsOpen}
          >
            {sessionsOpen ? "Masquer" : "Sessions"}
          </button>
        )}
      </div>

      {selectedMonument && (
        <div className="chat-monument-context" role="status">
          Contexte : {monumentDisplayName(selectedMonument)}
        </div>
      )}

      <SessionList
        chats={chats}
        activeChatId={activeChatId}
        open={sessionsOpen}
        onSelect={(id) => {
          onSelectChat(id);
          setSessionsOpen(false);
        }}
        onDelete={onDeleteChat}
      />

      <MessageList
        chat={chat}
        loading={loading}
        error={error}
        loadingMessage="Recherche dans les sources historiques…"
        onSuggestedAction={handleSuggestedAction}
        onWizardAnswer={(action, label) => void sendWizardAction(action, label)}
      />

      <form className="composer chat-widget-composer" onSubmit={handleSubmit}>
        <div className="composer-box">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Demandez quelque chose sur Carthage…"
            rows={1}
            disabled={loading}
            aria-label="Votre message"
          />
          <button
            type="submit"
            className="composer-send"
            disabled={loading || !input.trim()}
            aria-label="Envoyer le message"
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                fill="currentColor"
                d="M3.4 20.6 22 12 3.4 3.4l2.8 7.2L17 12l-10.8 1.4-2.8 7.2z"
              />
            </svg>
          </button>
        </div>
        <p className="composer-hint">Entrée pour envoyer · Maj+Entrée pour nouvelle ligne</p>
      </form>
    </div>
  );
}
