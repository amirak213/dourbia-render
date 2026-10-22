import type { ChatSession } from "../types";

interface SessionListProps {
  chats: ChatSession[];
  activeChatId: string | null;
  open: boolean;
  onSelect: (chatId: string) => void;
  onDelete: (chatId: string) => void;
}

function formatDate(timestamp: number): string {
  return new Date(timestamp).toLocaleDateString("fr-FR", {
    day: "numeric",
    month: "short",
  });
}

export default function SessionList({
  chats,
  activeChatId,
  open,
  onSelect,
  onDelete,
}: SessionListProps) {
  if (!open || chats.length === 0) return null;

  return (
    <div
      className="chat-widget-sessions chat-scroll"
      role="navigation"
      aria-label="Conversations"
    >
      <ul className="widget-session-list">
        {chats.map((chat) => (
          <li
            key={chat.id}
            className={chat.id === activeChatId ? "active" : undefined}
          >
            <button
              type="button"
              className="widget-session-item"
              onClick={() => onSelect(chat.id)}
            >
              <span className="widget-session-title">{chat.title}</span>
              <small className="widget-session-date">{formatDate(chat.updatedAt)}</small>
            </button>
            <button
              type="button"
              className="widget-session-delete"
              title="Supprimer"
              aria-label={`Supprimer ${chat.title}`}
              onClick={() => onDelete(chat.id)}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
