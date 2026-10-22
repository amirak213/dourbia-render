import HistoricalChat from "./chat/HistoricalChat";
import type { ChatSession } from "../types";

interface ChatWidgetProps {
  chat: ChatSession | null;
  chats: ChatSession[];
  activeChatId: string | null;
  onClose: () => void;
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

/** @deprecated Use HistoricalChat directly */
export default function ChatWidget(props: ChatWidgetProps) {
  return <HistoricalChat variant="floating" {...props} />;
}
