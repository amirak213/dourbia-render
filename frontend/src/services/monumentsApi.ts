import type { MonumentSummary } from "../types/monument";

const API_URL =
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "";

export async function fetchMonuments(): Promise<MonumentSummary[]> {
  const response = await fetch(`${API_URL}/api/monuments`);
  if (!response.ok) {
    throw new Error(`Impossible de charger les monuments (${response.status})`);
  }
  const data = (await response.json()) as { monuments: MonumentSummary[] };
  return data.monuments ?? [];
}
