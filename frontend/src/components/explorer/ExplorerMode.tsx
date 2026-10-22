import { PERIOD_OPTIONS } from "../../content/circuitContent";
import { useWorkspace } from "../../context/WorkspaceContext";
import type { ExplorerMonumentsState } from "../../hooks/useExplorerMonuments";
import type { MonumentSummary } from "../../types/monument";
import { monumentDisplayName } from "../../types/monument";
import MonumentCard from "../monuments/MonumentCard";

interface ExplorerModeProps {
  state: ExplorerMonumentsState;
  loading: boolean;
  error: string | null;
  selectedMonument: MonumentSummary | null;
  onViewOnMap: (monument: MonumentSummary) => void;
  onRetry?: () => void;
}

export default function ExplorerMode({
  state,
  loading,
  error,
  selectedMonument,
  onViewOnMap,
  onRetry,
}: ExplorerModeProps) {
  const {
    search,
    setSearch,
    periodFilter,
    setPeriodFilter,
    showAllCatalog,
    setShowAllCatalog,
    isFiltering,
    panelResults,
    totalCount,
  } = state;
  const { mustVisitMonuments, toggleMustVisit, openGuideWithQuestion } = useWorkspace();

  const sectionLabel = isFiltering
    ? `${panelResults.length} ${panelResults.length > 1 ? "résultats" : "résultat"}`
    : showAllCatalog
      ? "Tous les monuments"
      : "Suggestions pour commencer";

  return (
    <div className="explorer-mode">
      <div className="explorer-toolbar">
        <label className="explorer-search">
          <span className="sr-only">Rechercher un monument</span>
          <svg
            className="explorer-search-icon"
            viewBox="0 0 24 24"
            width="16"
            height="16"
            aria-hidden="true"
          >
            <path
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              d="m21 21-4.3-4.3M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Z"
            />
          </svg>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher un monument…"
          />
        </label>

        <div className="explorer-filters" role="group" aria-label="Filtrer par période">
          <button
            type="button"
            className={`explorer-filter-chip${periodFilter === null ? " active" : ""}`}
            aria-pressed={periodFilter === null}
            onClick={() => setPeriodFilter(null)}
          >
            Tous
          </button>
          {PERIOD_OPTIONS.map((period) => (
            <button
              key={period}
              type="button"
              className={`explorer-filter-chip${periodFilter === period ? " active" : ""}`}
              aria-pressed={periodFilter === period}
              onClick={() => setPeriodFilter(period)}
            >
              {period}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="explorer-empty" role="status">
          <p>Chargement des monuments de Carthage…</p>
        </div>
      ) : error ? (
        <div className="explorer-empty" role="alert">
          <p>Impossible de charger les monuments pour le moment.</p>
          {onRetry && (
            <button type="button" className="btn-mini btn-mini-primary" onClick={onRetry}>
              Réessayer
            </button>
          )}
        </div>
      ) : panelResults.length === 0 ? (
        <div className="explorer-empty">
          <p>Aucun monument ne correspond à votre recherche.</p>
        </div>
      ) : (
        <div className="explorer-card-list thin-scroll">
          <p className="explorer-section-label">{sectionLabel}</p>
          {panelResults.map((monument) => (
            <MonumentCard
              key={monument.id}
              monument={monument}
              selected={selectedMonument?.id === monument.id}
              isMustVisit={mustVisitMonuments.includes(monument.name_fr)}
              onViewOnMap={() => onViewOnMap(monument)}
              onAskGuide={() =>
                openGuideWithQuestion(
                  `Parle-moi des ${monumentDisplayName(monument)}`,
                  monument,
                )
              }
              onAddToCircuit={() => toggleMustVisit(monument.name_fr)}
            />
          ))}

          {!isFiltering && (
            <button
              type="button"
              className="explorer-show-all"
              onClick={() => setShowAllCatalog(!showAllCatalog)}
            >
              {showAllCatalog
                ? "Afficher les suggestions"
                : `Voir tous les monuments (${totalCount})`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
