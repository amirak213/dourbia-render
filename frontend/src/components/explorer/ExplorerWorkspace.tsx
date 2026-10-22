import { useCallback, useEffect, useMemo, useState } from "react";
import type { SiteView } from "../../content/siteContent";
import { useWorkspace } from "../../context/WorkspaceContext";
import { useExplorerMonuments } from "../../hooks/useExplorerMonuments";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { useMonuments } from "../../hooks/useMonuments";
import type { ChatSession, SourceRef } from "../../types";
import type { MonumentSummary } from "../../types/monument";
import { monumentDisplayName } from "../../types/monument";
import { matchSourceToMonuments } from "../map/mapUtils";
import {
  buildExplorerVisibleMonuments,
  resolveByIds,
  resolveByNames,
} from "../map/mapVisibility";
import DourbiaMap from "../map/DourbiaMap";
import ExplorerMapLayer from "../map/ExplorerMapLayer";
import MonumentDetailCard from "./MonumentDetailCard";
import ExplorerSidePanel from "./ExplorerSidePanel";

interface ExplorerWorkspaceProps {
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

export default function ExplorerWorkspace({
  onNavigate,
  chat,
  chats,
  activeChatId,
  onNewChat,
  onSelectChat,
  onDeleteChat,
  onEnsureChat,
  onAppendMessage,
}: ExplorerWorkspaceProps) {
  const { monuments, loading, error, refetch } = useMonuments();
  const explorerState = useExplorerMonuments(monuments);
  const [panelOpen, setPanelOpen] = useState(true);
  const [mobileView, setMobileView] = useState<"map" | "panel">("panel");
  const [toast, setToast] = useState<string | null>(null);
  const {
    selectedMonument,
    setSelectedMonument,
    historicalContextIds,
    pushHistoricalContext,
    mustVisitMonuments,
    toggleMustVisit,
    showAllOnMap,
    setShowAllOnMap,
    openGuideWithQuestion,
  } = useWorkspace();

  const isMobile = useMediaQuery("(max-width: 767px)");
  const showPanel = isMobile ? mobileView === "panel" : panelOpen;
  const showMap = isMobile ? mobileView === "map" : true;

  const catalogById = useMemo(
    () => new Map(monuments.map((m) => [m.id, m])),
    [monuments],
  );

  const desiredMonuments = useMemo(
    () => resolveByNames(monuments, mustVisitMonuments),
    [monuments, mustVisitMonuments],
  );
  const desiredIds = useMemo(
    () => new Set(desiredMonuments.map((m) => m.id)),
    [desiredMonuments],
  );

  const historicalMonuments = useMemo(
    () => resolveByIds(catalogById, historicalContextIds),
    [catalogById, historicalContextIds],
  );
  const historicalIds = useMemo(
    () => new Set(historicalContextIds),
    [historicalContextIds],
  );

  const visibleMonuments = useMemo(() => {
    if (showAllOnMap) return monuments;
    return buildExplorerVisibleMonuments({
      selected: selectedMonument,
      historical: historicalMonuments,
      desired: desiredMonuments,
      suggestions: explorerState.mapResults,
    });
  }, [
    showAllOnMap,
    monuments,
    selectedMonument,
    historicalMonuments,
    desiredMonuments,
    explorerState.mapResults,
  ]);

  const showConfirmation = useCallback((message: string) => {
    setToast(message);
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  const handleSourcesReceived = useCallback(
    (sources: SourceRef[] | undefined) => {
      if (!sources || sources.length === 0) return;
      const matched = matchSourceToMonuments(sources, monuments);
      if (matched.length > 0) {
        pushHistoricalContext(matched.map((m) => m.id));
        setSelectedMonument(matched[0]);
      }
    },
    [monuments, pushHistoricalContext, setSelectedMonument],
  );

  function handleViewOnMap(monument: MonumentSummary) {
    setSelectedMonument(monument);
    setMobileView("map");
  }

  function handleAskGuide(monument: MonumentSummary) {
    openGuideWithQuestion(`Parle-moi des ${monument.name_fr}`, monument);
    setMobileView("panel");
  }

  function handleAddToCircuit(monument: MonumentSummary) {
    const alreadyDesired = mustVisitMonuments.includes(monument.name_fr);
    toggleMustVisit(monument.name_fr);
    showConfirmation(
      alreadyDesired
        ? `${monumentDisplayName(monument)} retiré de vos souhaits.`
        : `${monumentDisplayName(monument)} ajouté à vos souhaits.`,
    );
  }

  return (
    <section
      className={`explorer-workspace${mobileView === "map" ? " mobile-map-view" : " mobile-panel-view"}`}
    >
      <div className={`explorer-layout${panelOpen ? "" : " panel-collapsed"}`}>
        {showPanel && (
          <ExplorerSidePanel
            explorerState={explorerState}
            monumentsLoading={loading}
            monumentsError={error}
            selectedMonument={selectedMonument}
            onViewOnMap={handleViewOnMap}
            onRetryMonuments={refetch}
            onNavigate={onNavigate}
            chat={chat}
            chats={chats}
            activeChatId={activeChatId}
            onNewChat={onNewChat}
            onSelectChat={onSelectChat}
            onDeleteChat={onDeleteChat}
            onEnsureChat={onEnsureChat}
            onAppendMessage={onAppendMessage}
            onSourcesReceived={handleSourcesReceived}
          />
        )}

        {showMap && (
          <div
            className={`explorer-map-column${mobileView === "map" ? " mobile-active" : ""}`}
          >
            <div className="explorer-map-toolbar">
              <button
                type="button"
                className="explorer-panel-toggle"
                onClick={() => setPanelOpen((open) => !open)}
                aria-label={panelOpen ? "Masquer le panneau" : "Afficher le panneau"}
              >
                {panelOpen ? "◀" : "▶"}
              </button>
              <div className="explorer-mobile-tabs">
                <button
                  type="button"
                  className={mobileView === "panel" ? "active" : ""}
                  onClick={() => setMobileView("panel")}
                >
                  Panneau
                </button>
                <button
                  type="button"
                  className={mobileView === "map" ? "active" : ""}
                  onClick={() => setMobileView("map")}
                >
                  Carte
                </button>
              </div>
            </div>

            <div className="explorer-map-frame">
              <DourbiaMap>
                <ExplorerMapLayer
                  monuments={visibleMonuments}
                  selectedMonument={selectedMonument}
                  desiredIds={desiredIds}
                  historicalIds={historicalIds}
                  onSelectMonument={handleViewOnMap}
                  onAskGuide={handleAskGuide}
                  onAddToCircuit={handleAddToCircuit}
                />
              </DourbiaMap>

              <label className="explorer-map-showall">
                <input
                  type="checkbox"
                  checked={showAllOnMap}
                  onChange={(e) => setShowAllOnMap(e.target.checked)}
                />
                Afficher tous les monuments
              </label>

              {toast && (
                <div className="explorer-map-toast" role="status">
                  {toast}
                </div>
              )}
            </div>

            {selectedMonument && mobileView === "map" && (
              <div className="explorer-mobile-sheet">
                <MonumentDetailCard
                  monument={selectedMonument}
                  isMustVisit={mustVisitMonuments.includes(selectedMonument.name_fr)}
                  onAskGuide={() => handleAskGuide(selectedMonument)}
                  onAddToCircuit={() => handleAddToCircuit(selectedMonument)}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
