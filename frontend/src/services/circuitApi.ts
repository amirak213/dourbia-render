import type {
  CircuitFormState,
  CircuitRecommendRequest,
  CircuitRecommendResponse,
} from "../types/circuit";

const API_URL =
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "";

const CIRCUIT_TIMEOUT_MS = 60_000;

function formatCircuitError(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") {
    return (
      "L'optimisation prend trop de temps. Vérifiez que l'API tourne " +
      "et que les données de circuits sont importées."
    );
  }
  if (error instanceof TypeError) {
    return (
      "Impossible de joindre l'API. Démarrez le backend avec " +
      "`uvicorn app.main:app --reload`."
    );
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Erreur inconnue lors de la recommandation de circuit.";
}

export function buildCircuitPayload(
  form: CircuitFormState,
  sessionId: string,
): CircuitRecommendRequest {
  const duration = form.duration_minutes.trim()
    ? Number(form.duration_minutes)
    : undefined;

  return {
    session_id: sessionId,
    type_tarif: form.type_tarif,
    budget_max: Number(form.budget_max),
    transport: form.transport,
    mobilite: form.mobilite,
    duration_minutes: Number.isFinite(duration) ? duration : undefined,
    start_time: form.start_time || null,
    end_time: form.end_time || null,
    zone: "Carthage",
    preferences: {
      epoques: form.epoques,
      fonctions: form.fonctions,
      must_visit: form.must_visit,
      avoid: [],
    },
    start_location: null,
    end_location: null,
  };
}

export async function recommendCircuit(
  payload: CircuitRecommendRequest,
): Promise<CircuitRecommendResponse> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), CIRCUIT_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}/api/circuits/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });

    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      throw new Error("Réponse API invalide.");
    }

    if (!response.ok) {
      const detail =
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
          ? body.detail
          : "Impossible de générer un circuit avec ces contraintes. Essayez d'élargir la durée ou le budget.";
      throw new Error(detail);
    }

    return body as CircuitRecommendResponse;
  } catch (error) {
    throw new Error(formatCircuitError(error));
  } finally {
    window.clearTimeout(timeoutId);
  }
}
