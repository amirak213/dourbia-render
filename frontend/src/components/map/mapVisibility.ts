import type { MonumentSummary } from "../../types/monument";

export const MAX_HISTORICAL_CONTEXT = 5;
export const MAX_EXPLORER_MAP_MARKERS = 10;

export type MarkerCategory =
  | "generated"
  | "desired"
  | "selected"
  | "historical"
  | "suggestion";

/**
 * Deduplicate monuments by their stable id, preserving order and keeping the
 * first occurrence. Ids may be fractional (e.g. 3.9) and must not be coerced.
 */
export function dedupeById(monuments: MonumentSummary[]): MonumentSummary[] {
  const seen = new Set<number>();
  const result: MonumentSummary[] = [];
  for (const monument of monuments) {
    if (seen.has(monument.id)) continue;
    seen.add(monument.id);
    result.push(monument);
  }
  return result;
}

/**
 * LRU update for the bounded historical-context list. Newly discussed ids are
 * moved to the end (most-recent); when the limit is exceeded the oldest ids at
 * the front are dropped. Returns a new array (never mutates the input).
 */
export function appendHistoricalContext(
  current: number[],
  incoming: number[],
  limit: number = MAX_HISTORICAL_CONTEXT,
): number[] {
  const next = current.filter((id) => !incoming.includes(id));
  next.push(...dedupeNumbers(incoming));
  if (next.length <= limit) return next;
  return next.slice(next.length - limit);
}

function dedupeNumbers(values: number[]): number[] {
  const seen = new Set<number>();
  const result: number[] = [];
  for (const value of values) {
    if (seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
}

export interface VisibleMonumentGroups {
  selected: MonumentSummary | null;
  historical: MonumentSummary[];
  desired: MonumentSummary[];
  suggestions: MonumentSummary[];
}

/**
 * Build the deduplicated union of monuments that should be visible on the
 * Explorer map. Selected, historical (LRU) and desired monuments are always
 * kept; suggestions/search results are appended up to a marker cap.
 */
export function buildExplorerVisibleMonuments(
  groups: VisibleMonumentGroups,
  maxSuggestions: number = MAX_EXPLORER_MAP_MARKERS,
): MonumentSummary[] {
  const priority: MonumentSummary[] = [];
  if (groups.selected) priority.push(groups.selected);
  priority.push(...groups.desired);
  priority.push(...groups.historical);
  const cappedSuggestions = groups.suggestions.slice(0, maxSuggestions);
  return dedupeById([...priority, ...cappedSuggestions]);
}

export interface MarkerCategoryInput {
  selectedId: number | null;
  desiredIds: ReadonlySet<number>;
  historicalIds: ReadonlySet<number>;
}

/**
 * Resolve the single visual category for a monument marker.
 * Priority: generated circuit > desired > selected > historical > suggestion.
 * (Generated-circuit markers are rendered by CircuitRouteLayer, not here.)
 */
export function markerCategory(
  id: number,
  input: MarkerCategoryInput,
): MarkerCategory {
  if (input.desiredIds.has(id)) return "desired";
  if (input.selectedId != null && id === input.selectedId) return "selected";
  if (input.historicalIds.has(id)) return "historical";
  return "suggestion";
}

/**
 * Resolve catalog monuments from a list of display names (used for the desired
 * / must-visit set which is stored as name_fr strings). Matching is exact on
 * name_fr to stay consistent with the circuit form contract.
 */
export function resolveByNames(
  monuments: MonumentSummary[],
  names: string[],
): MonumentSummary[] {
  const wanted = new Set(names);
  return monuments.filter((m) => wanted.has(m.name_fr));
}

/**
 * Resolve catalog monuments from a list of ids, preserving the id order and
 * skipping ids that are not in the catalog.
 */
export function resolveByIds(
  byId: Map<number, MonumentSummary>,
  ids: number[],
): MonumentSummary[] {
  const result: MonumentSummary[] = [];
  for (const id of ids) {
    const monument = byId.get(id);
    if (monument) result.push(monument);
  }
  return result;
}

/**
 * Stable signature for a set of positions. Used to guarantee a camera fit runs
 * at most once per distinct geometry (prevents refit-on-every-render).
 */
export function positionsSignature(positions: [number, number][]): string {
  return positions.map(([lat, lng]) => `${lat},${lng}`).join("|");
}
