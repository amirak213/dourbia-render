import type { SourceRef } from "../../types";
import type { MonumentSummary } from "../../types/monument";

function normalizeName(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^\w\s']/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function matchSourceToMonuments(
  sources: SourceRef[],
  monuments: MonumentSummary[],
): MonumentSummary[] {
  const monumentSources = sources.filter((s) => s.source_type === "monument");
  if (monumentSources.length === 0) return [];

  const byId = new Map(monuments.map((m) => [m.id, m]));
  const byName = new Map(monuments.map((m) => [normalizeName(m.name_fr), m]));

  const matched: MonumentSummary[] = [];
  const seen = new Set<number>();

  const sorted = [...monumentSources].sort(
    (a, b) => (b.score ?? 0) - (a.score ?? 0),
  );

  for (const source of sorted) {
    let monument: MonumentSummary | undefined;
    if (source.source_id != null) {
      monument = byId.get(source.source_id);
    }
    if (!monument && source.title) {
      monument = byName.get(normalizeName(source.title));
    }
    if (monument && !seen.has(monument.id)) {
      seen.add(monument.id);
      matched.push(monument);
    }
  }

  return matched;
}

export function primaryFocusedId(matched: MonumentSummary[]): number | null {
  return matched.length > 0 ? matched[0].id : null;
}

export const CARTHAGE_CENTER: [number, number] = [36.857, 10.33];
export const CARTHAGE_DEFAULT_ZOOM = 14;
