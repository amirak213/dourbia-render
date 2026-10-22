import type { ChatSession } from "../types";
import SessionList from "../components/SessionList";
import Button from "../components/ui/Button";

interface SessionsPageProps {
  chats: ChatSession[];
  activeChatId: string | null;
  onSelectChat: (chatId: string) => void;
  onDeleteChat: (chatId: string) => void;
  onNewChat: () => void;
  onOpenChat: () => void;
}

export default function SessionsPage({
  chats,
  activeChatId,
  onSelectChat,
  onDeleteChat,
  onNewChat,
  onOpenChat,
}: SessionsPageProps) {
  return (
    <section className="content-panel sessions-page">
      <header className="page-header">
        <h1>Mes sessions</h1>
        <p>Retrouvez vos conversations avec le guide historique de Carthage.</p>
      </header>

      <div className="sessions-page-actions">
        <Button variant="primary" onClick={onNewChat}>
          Nouvelle conversation
        </Button>
      </div>

      {chats.length === 0 ? (
        <div className="explorer-empty">
          <p>Posez une question sur Carthage, ses monuments ou son histoire.</p>
          <Button variant="secondary" onClick={onOpenChat}>
            Parler au guide
          </Button>
        </div>
      ) : (
        <SessionList
          chats={chats}
          activeChatId={activeChatId}
          open
          onSelect={(id) => {
            onSelectChat(id);
            onOpenChat();
          }}
          onDelete={onDeleteChat}
        />
      )}
    </section>
  );
}
