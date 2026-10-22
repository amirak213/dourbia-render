import type { SiteView } from "../content/siteContent";
import type { ChatSession } from "../types";
import ExplorerWorkspace from "../components/explorer/ExplorerWorkspace";

interface ExplorerPageProps {
  onNavigate: (view: SiteView) => void;
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
      elapsedMs?: number;
      latencyMs?: number;
      latencyDebug?: ChatSession["messages"][number]["latencyDebug"];
    },
  ) => void;
}

export default function ExplorerPage(props: ExplorerPageProps) {
  return (
    <section className="page-section explorer-page">
      <ExplorerWorkspace {...props} />
    </section>
  );
}
