import { useMemo, useState } from "react";
import { MAX_EXPLORER_MAP_MARKERS } from "../components/map/mapVisibility";
import type { MonumentSummary } from "../types/monument";
import { monumentDisplayName } from "../types/monument";

const SUGGESTION_LIMIT = 6;

/** Curated names shown by default; resolved against the catalog by contains-match. */
const CURATED_SUGGESTION_NAMES = [
  "Thermes d'Antonin",
  "Tophet",
  "Ports puniques",
  "Byrsa",
  "Musée national de Carthage",
  "Théâtre",
];

function normalize(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function buildSuggestions(monuments: MonumentSummary[]): MonumentSummary[] {
  const picked: MonumentSummary[] = [];
  const usedIds = new Set<number>();

  for (const wanted of CURATED_SUGGESTION_NAMES) {
    const needle = normalize(wanted);
    const match = monuments.find(
      (m) => !usedIds.has(m.id) && normalize(m.name_fr).includes(needle),
    );
    if (match) {
      usedIds.add(match.id);
      picked.push(match);
    }
  }

  if (picked.length < SUGGESTION_LIMIT) {
    const byPopularity = [...monuments].sort(
      (a, b) => (b.popularity ?? 0) - (a.popularity ?? 0),
    );
    for (const monument of byPopularity) {
      if (picked.length >= SUGGESTION_LIMIT) break;
      if (usedIds.has(monument.id)) continue;
      usedIds.add(monument.id);
      picked.push(monument);
    }
  }

  return picked.slice(0, SUGGESTION_LIMIT);
}

export interface ExplorerMonumentsState {
  search: string;
  setSearch: (value: string) => void;
  periodFilter: string | null;
  setPeriodFilter: (value: string | null) => void;
  showAllCatalog: boolean;
  setShowAllCatalog: (value: boolean) => void;
  isFiltering: boolean;
  suggestions: MonumentSummary[];
  /** Monuments listed in the Explorer panel. */
  panelResults: MonumentSummary[];
  /** Monuments to render on the map (capped when searching). */
  mapResults: MonumentSummary[];
  totalCount: number;
}

export function useExplorerMonuments(
  monuments: MonumentSummary[],
): ExplorerMonumentsState {
  const [search, setSearch] = useState("");
  const [periodFilter, setPeriodFilter] = useState<string | null>(null);
  const [showAllCatalog, setShowAllCatalog] = useState(false);

  const suggestions = useMemo(() => buildSuggestions(monuments), [monuments]);

  const query = search.trim().toLowerCase();
  const isFiltering = query.length > 0 || periodFilter !== null;

  const filtered = useMemo(() => {
    if (!isFiltering) return [];
    return monuments.filter((monument) => {
      const name = monumentDisplayName(monument).toLowerCase();
      const matchesSearch = !query || name.includes(query);
      const matchesPeriod =
        !periodFilter || monument.dominant_period === periodFilter;
      return matchesSearch && matchesPeriod;
    });
  }, [monuments, query, periodFilter, isFiltering]);

  const panelResults = isFiltering
    ? filtered
    : showAllCatalog
      ? monuments
      : suggestions;

  const mapResults = isFiltering
    ? filtered.slice(0, MAX_EXPLORER_MAP_MARKERS)
    : suggestions;

  return {
    search,
    setSearch,
    periodFilter,
    setPeriodFilter,
    showAllCatalog,
    setShowAllCatalog,
    isFiltering,
    suggestions,
    panelResults,
    mapResults,
    totalCount: monuments.length,
  };
}
