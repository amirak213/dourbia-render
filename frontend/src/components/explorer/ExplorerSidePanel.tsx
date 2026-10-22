import type { SiteView } from "../../content/siteContent";
import { useWorkspace, type PanelMode } from "../../context/WorkspaceContext";
import type { ExplorerMonumentsState } from "../../hooks/useExplorerMonuments";
import type { ChatSession, SourceRef } from "../../types";
import HistoricalChat from "../chat/HistoricalChat";
import CircuitShortcutPanel from "./CircuitShortcutPanel";
import ExplorerMode from "./ExplorerMode";
import type { MonumentSummary } from "../../types/monument";

const PANEL_TABS: { id: PanelMode; label: string }[] = [
  { id: "explorer", label: "Explorer" },
  { id: "guide", label: "Guide historique" },
  { id: "circuit", label: "Mon circuit" },
];

interface ExplorerSidePanelProps {
  explorerState: ExplorerMonumentsState;
  monumentsLoading: boolean;
  monumentsError: string | null;
  selectedMonument: MonumentSummary | null;
  onViewOnMap: (monument: MonumentSummary) => void;
  onRetryMonuments: () => void;
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
  onSourcesReceived?: (sources: SourceRef[] | undefined) => void;
}

export default function ExplorerSidePanel({
  explorerState,
  monumentsLoading,
  monumentsError,
  selectedMonument,
  onViewOnMap,
  onRetryMonuments,
  onNavigate,
  chat,
  chats,
  activeChatId,
  onNewChat,
  onSelectChat,
  onDeleteChat,
  onEnsureChat,
  onAppendMessage,
  onSourcesReceived,
}: ExplorerSidePanelProps) {
  const { panelMode, setPanelMode } = useWorkspace();

  return (
    <aside className="explorer-side-panel">
      <div className="explorer-panel-tabs" role="tablist" aria-label="Modes du panneau">
        {PANEL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={panelMode === tab.id}
            className={`explorer-panel-tab${panelMode === tab.id ? " active" : ""}`}
            onClick={() => setPanelMode(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="explorer-panel-content">
        {panelMode === "explorer" && (
          <ExplorerMode
            state={explorerState}
            loading={monumentsLoading}
            error={monumentsError}
            selectedMonument={selectedMonument}
            onViewOnMap={onViewOnMap}
            onRetry={onRetryMonuments}
          />
        )}
        {panelMode === "guide" && (
          <HistoricalChat
            variant="docked"
            chat={chat}
            chats={chats}
            activeChatId={activeChatId}
            onClose={() => setPanelMode("explorer")}
            onNewChat={onNewChat}
            onSelectChat={onSelectChat}
            onDeleteChat={onDeleteChat}
            onEnsureChat={onEnsureChat}
            onAppendMessage={onAppendMessage}
            onSourcesReceived={onSourcesReceived}
          />
        )}
        {panelMode === "circuit" && (
          <CircuitShortcutPanel onNavigate={onNavigate} />
        )}
      </div>
    </aside>
  );
}
