import { useState } from "react";
import ChatLauncher from "./components/ChatLauncher";
import HistoricalChat from "./components/chat/HistoricalChat";
import EmbedBridge from "./embed/EmbedBridge";
import Footer from "./components/layout/Footer";
import Navbar from "./components/layout/Navbar";
import PageContainer from "./components/layout/PageContainer";
import SitePages from "./components/SitePages";
import { WorkspaceProvider, useWorkspace } from "./context/WorkspaceContext";
import type { SiteView } from "./content/siteContent";
import { useChats } from "./hooks/useChats";
import { matchSourceToMonuments } from "./components/map/mapUtils";
import { useMonuments } from "./hooks/useMonuments";
import type { SourceRef } from "./types";
import "./App.css";

function AppContent() {
  const [activeView, setActiveView] = useState<SiteView>("home");
  const {
    chatDisplayMode,
    setChatDisplayMode,
    setPanelMode,
    openGuideWithQuestion,
    pushHistoricalContext,
    setSelectedMonument,
    activeCircuit,
  } = useWorkspace();
  const { monuments } = useMonuments();
  const {
    chats,
    activeChat,
    activeChatId,
    startNewChat,
    selectChat,
    deleteChat,
    appendMessage,
    ensureActiveChat,
  } = useChats();

  const widgetOpen = chatDisplayMode === "floating";

  function handleNewChat() {
    startNewChat();
    setChatDisplayMode("floating");
    setActiveView("explorer");
    setPanelMode("guide");
  }

  function handleOpenChat() {
    setChatDisplayMode("floating");
  }

  function handleCloseChat() {
    setChatDisplayMode("hidden");
  }

  function handleAskGuide(question: string) {
    openGuideWithQuestion(question);
    setActiveView("explorer");
    setChatDisplayMode("docked");
  }

  function handleSourcesReceived(sources: SourceRef[] | undefined) {
    if (!sources || sources.length === 0) return;
    const matched = matchSourceToMonuments(sources, monuments);
    if (matched.length > 0) {
      pushHistoricalContext(matched.map((m) => m.id));
      setSelectedMonument(matched[0]);
    }
  }

  const isExplorer = activeView === "explorer";
  const isChatEmbed =
    new URLSearchParams(window.location.search).get("embed") === "chat";

  if (isChatEmbed) {
    return (
      <div className="app-shell app-shell--chat-embed">
        <HistoricalChat
          variant="docked"
          chat={activeChat}
          chats={chats}
          activeChatId={activeChatId}
          onClose={handleCloseChat}
          onNewChat={startNewChat}
          onSelectChat={selectChat}
          onDeleteChat={deleteChat}
          onEnsureChat={ensureActiveChat}
          onAppendMessage={appendMessage}
          onSourcesReceived={handleSourcesReceived}
        />
        <EmbedBridge mapOpen={Boolean(activeCircuit)} />
      </div>
    );
  }

  return (
    <div className={`app-shell${isExplorer ? " app-shell-explorer" : ""}`}>
      <Navbar
        activeView={activeView}
        onNavigate={setActiveView}
        onNewChat={handleNewChat}
      />
      <div className="main-stage">
        {isExplorer ? (
          <SitePages
            view={activeView}
            onNavigate={setActiveView}
            onOpenChat={handleOpenChat}
            onAskGuide={handleAskGuide}
            chat={activeChat}
            chats={chats}
            activeChatId={activeChatId}
            onNewChat={startNewChat}
            onSelectChat={selectChat}
            onDeleteChat={deleteChat}
            onEnsureChat={ensureActiveChat}
            onAppendMessage={appendMessage}
          />
        ) : (
          <PageContainer>
            <SitePages
              view={activeView}
              onNavigate={setActiveView}
              onOpenChat={handleOpenChat}
              onAskGuide={handleAskGuide}
              chat={activeChat}
              chats={chats}
              activeChatId={activeChatId}
              onNewChat={startNewChat}
              onSelectChat={selectChat}
              onDeleteChat={deleteChat}
              onEnsureChat={ensureActiveChat}
              onAppendMessage={appendMessage}
            />
          </PageContainer>
        )}
      </div>
      <Footer />

      {chatDisplayMode !== "docked" && (
        <ChatLauncher open={widgetOpen} onToggle={handleOpenChat} />
      )}
      {widgetOpen && (
        <HistoricalChat
          variant="floating"
          chat={activeChat}
          chats={chats}
          activeChatId={activeChatId}
          onClose={handleCloseChat}
          onNewChat={startNewChat}
          onSelectChat={selectChat}
          onDeleteChat={deleteChat}
          onEnsureChat={ensureActiveChat}
          onAppendMessage={appendMessage}
          onSourcesReceived={handleSourcesReceived}
        />
      )}
    </div>
  );
}

export default function App() {
  return (
    <WorkspaceProvider>
      <AppContent />
    </WorkspaceProvider>
  );
}
