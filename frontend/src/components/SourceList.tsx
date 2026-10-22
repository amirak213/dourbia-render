import { useState } from "react";
import type { SourceRef } from "../types";

interface SourceListProps {
  sources: SourceRef[];
}

function formatLocalMeta(source: SourceRef): string {
  if (source.score != null) {
    return `${source.source_type} · ${source.score.toFixed(2)}`;
  }
  return source.source_type;
}

function webProvider(source: SourceRef): string | null {
  if (source.provider) return source.provider;
  if (!source.url) return null;
  try {
    return new URL(source.url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

export default function SourceList({ sources }: SourceListProps) {
  const [open, setOpen] = useState(false);

  const localSources = sources.filter((s) => s.source_type !== "web");
  const webSources = sources.filter((s) => s.source_type === "web");

  if (sources.length === 0) return null;

  return (
    <div className="source-list-wrap">
      <button
        type="button"
        className="details-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? "Masquer les sources" : `Sources (${sources.length})`}
      </button>
      {open && (
        <div className="details-panel source-panel">
          {localSources.length > 0 && (
            <section>
              <h4>Sources internes</h4>
              <ul className="source-list">
                {localSources.map((source, index) => (
                  <li key={`local-${source.source_id ?? index}-${source.title ?? index}`}>
                    <strong>{source.title ?? "Sans titre"}</strong>
                    <span>{formatLocalMeta(source)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {webSources.length > 0 && (
            <section className={localSources.length > 0 ? "details-section-spaced" : undefined}>
              <h4>Sources web</h4>
              <ul className="source-list">
                {webSources.map((source, index) => (
                  <li key={`web-${index}-${source.title ?? index}`}>
                    <strong>{source.title ?? "Source web"}</strong>
                    {webProvider(source) && (
                      <span className="source-provider">{webProvider(source)}</span>
                    )}
                    {source.url && (
                      <a
                        className="source-link"
                        href={source.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {source.url}
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
