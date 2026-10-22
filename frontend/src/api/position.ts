const API_URL =
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "";

export interface PositionPayload {
  user_id?: string;
  session_id?: string;
  latitude: number;
  longitude: number;
  langue?: string;
}

export interface PositionResponse {
  triggered: boolean;
  monument?: string | null;
  monument_id?: string | null;
  distance_m?: number | null;
}

export async function sendPositionUpdate(payload: PositionPayload): Promise<PositionResponse> {
  const response = await fetch(`${API_URL}/api/position`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error("Impossible d'envoyer la position au backend.");
  }

  return response.json();
}
