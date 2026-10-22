import type { ChatResponse, WizardAction } from "../types";

const API_URL =
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "";
const CHAT_TIMEOUT_MS = 45_000;

export type ChatLanguage = "auto" | "fr" | "en" | "ar";

export interface ChatApiResult extends ChatResponse {
  clientElapsedMs: number;
}

export function formatChatError(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return (
      "Le serveur met trop de temps à répondre. Vérifiez que l'API tourne " +
      "(uvicorn) et que PostgreSQL est démarré (`docker compose up -d`)."
    );
  }
  if (error instanceof TypeError) {
    return (
      "Impossible de joindre l'API sur le port 8000. " +
      "Démarrez le backend avec `uvicorn app.main:app --reload`."
    );
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Impossible d'obtenir une réponse pour le moment. Réessayez.";
}

export async function sendChatMessage(
  sessionId: string,
  message: string,
  language: ChatLanguage = "auto",
  action?: WizardAction,
): Promise<ChatApiResult> {
  const started = performance.now();
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message, language, action }),
      signal: controller.signal,
    });

    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      throw new Error("Réponse API invalide. Vérifiez les logs du backend.");
    }

    const clientElapsedMs = performance.now() - started;
    if (!response.ok) {
      const detail =
        typeof payload === "object" &&
        payload !== null &&
        "detail" in payload &&
        typeof payload.detail === "string"
          ? payload.detail
          : "Erreur lors de l'appel à l'API";
      throw new Error(detail);
    }

    return { ...(payload as ChatResponse), clientElapsedMs };
  } catch (error) {
    throw new Error(formatChatError(error));
  } finally {
    window.clearTimeout(timeoutId);
  }
}
