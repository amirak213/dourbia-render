import type { MapRoutePayload } from "./types/circuit";
export interface SourceRef {
  source_type: string;
  source_id: number | null;
  title: string | null;
  score: number | null;
  url?: string | null;
  provider?: string | null;
}

export interface MemoryContext {
  preferred_language: string;
  interests: string[];
  available_time_minutes: number | null;
  mobility_mode: string | null;
  last_mentioned_monuments: string[];
  primary_site_id: number | null;
  primary_site_name: string | null;
  last_substantive_user_message?: string | null;
}

export interface LatencyDebug {
  memory_retrieval_ms?: number | null;
  retrieval_ms?: number | null;
  prompt_construction_ms?: number | null;
  llm_generation_ms?: number | null;
  memory_update_ms?: number | null;
  web_search_ms?: number | null;
}

export type WizardInputType =
  | "single_select"
  | "multi_select"
  | "budget_form"
  | "mobility_form"
  | "time_form"
  | "preferences_form"
  | "confirm";

export interface WizardOption {
  value: string;
  label: string;
  meta?: Record<string, unknown> | null;
}

export interface WizardCircuitStop {
  order: number;
  name: string;
  visit_duration_min: number;
  price: number | null;
  latitude?: number | null;
  longitude?: number | null;
}

export interface WizardCircuitSummary {
  title: string;
  summary: string;
  monuments: WizardCircuitStop[];
  total_duration_min: number;
  total_price: number;
  budget_max?: number | null;
  unknown_price_count: number;
  route?: MapRoutePayload;
}

export interface WizardUI {
  state: string;
  question: string;
  input_type: WizardInputType;
  options: WizardOption[];
  has_more: boolean;
  budget_ok?: boolean | null;
  budget_warning?: string | null;
  circuit?: WizardCircuitSummary | null;
}

/** Payload envoyé au backend en réponse à une card du wizard. */
export interface WizardAction {
  type: string;
  value?: unknown;
}

export interface PackCard {
  code?: string | null;
  title: string;
  emoji: string;
  description?: string | null;
  duration?: string | null;
  capacity?: number | null;
  audience?: string | null;
  location?: string | null;
}

export interface ChatResponse {
  session_id: string;
  answer: string;
  sources: SourceRef[];
  memory_context: MemoryContext;
  suggested_actions: string[];
  latency_ms?: number | null;
  latency_debug?: LatencyDebug | null;
  wizard_ui?: WizardUI | null;
  packs?: PackCard[] | null;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceRef[];
  memory?: MemoryContext;
  actions?: string[];
  wizard?: WizardUI | null;
  packs?: PackCard[] | null;
  elapsedMs?: number;
  latencyMs?: number;
  latencyDebug?: LatencyDebug;
  createdAt: number;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}
