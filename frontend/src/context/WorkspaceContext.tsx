import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { MonumentSummary } from "../types/monument";
import { appendHistoricalContext } from "../components/map/mapVisibility";
import type { WizardCircuitSummary } from "../types";

export type PanelMode = "explorer" | "guide" | "circuit";
export type ChatDisplayMode = "floating" | "docked" | "hidden";

interface WorkspaceContextValue {
  panelMode: PanelMode;
  setPanelMode: (mode: PanelMode) => void;
  selectedMonument: MonumentSummary | null;
  setSelectedMonument: (monument: MonumentSummary | null) => void;
  /** Bounded (LRU) list of monument ids discussed with HistoricalAgent. */
  historicalContextIds: number[];
  pushHistoricalContext: (ids: number[]) => void;
  mustVisitMonuments: string[];
  toggleMustVisit: (name: string) => void;
  setMustVisitMonuments: (names: string[]) => void;
  showAllOnMap: boolean;
  setShowAllOnMap: (value: boolean) => void;
  chatDisplayMode: ChatDisplayMode;
  setChatDisplayMode: (mode: ChatDisplayMode) => void;
  pendingGuideQuestion: string | null;
  setPendingGuideQuestion: (question: string | null) => void;
  openGuideWithQuestion: (question: string, monument?: MonumentSummary | null) => void;
  activeCircuit: WizardCircuitSummary | null;
  setActiveCircuit: (circuit: WizardCircuitSummary | null) => void;
  guideEnabled: boolean;
  setGuideEnabled: (enabled: boolean) => void;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [panelMode, setPanelMode] = useState<PanelMode>("explorer");
  const [selectedMonument, setSelectedMonument] = useState<MonumentSummary | null>(null);
  const [historicalContextIds, setHistoricalContextIds] = useState<number[]>([]);
  const [mustVisitMonuments, setMustVisitMonuments] = useState<string[]>([]);
  const [showAllOnMap, setShowAllOnMap] = useState(false);
  const [chatDisplayMode, setChatDisplayMode] = useState<ChatDisplayMode>("hidden");
  const [pendingGuideQuestion, setPendingGuideQuestion] = useState<string | null>(null);
  const [activeCircuit, setActiveCircuit] = useState<WizardCircuitSummary | null>(null);
  const [guideEnabled, setGuideEnabled] = useState(false);

  const pushHistoricalContext = useCallback((ids: number[]) => {
    if (ids.length === 0) return;
    setHistoricalContextIds((current) => appendHistoricalContext(current, ids));
  }, []);

  const toggleMustVisit = useCallback((name: string) => {
    setMustVisitMonuments((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  }, []);

  const openGuideWithQuestion = useCallback(
    (question: string, monument?: MonumentSummary | null) => {
      if (monument) {
        setSelectedMonument(monument);
      }
      setPendingGuideQuestion(question);
      setPanelMode("guide");
      setChatDisplayMode("docked");
    },
    [],
  );

  const value = useMemo(
    () => ({
      panelMode,
      setPanelMode,
      selectedMonument,
      setSelectedMonument,
      historicalContextIds,
      pushHistoricalContext,
      mustVisitMonuments,
      toggleMustVisit,
      setMustVisitMonuments,
      showAllOnMap,
      setShowAllOnMap,
      chatDisplayMode,
      setChatDisplayMode,
      pendingGuideQuestion,
      setPendingGuideQuestion,
      openGuideWithQuestion,
      activeCircuit,
      setActiveCircuit,
      guideEnabled,
      setGuideEnabled,
    }),
    [
      panelMode,
      selectedMonument,
      historicalContextIds,
      pushHistoricalContext,
      mustVisitMonuments,
      toggleMustVisit,
      showAllOnMap,
      chatDisplayMode,
      pendingGuideQuestion,
      openGuideWithQuestion,
      activeCircuit,
      guideEnabled,
    ],
  );

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const context = useContext(WorkspaceContext);
  if (!context) {
    throw new Error("useWorkspace must be used within WorkspaceProvider");
  }
  return context;
}
