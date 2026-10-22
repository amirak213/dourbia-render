import type { PackCard } from "../types";

interface PackCardGridProps {
  packs: PackCard[];
}

export default function PackCardGrid({ packs }: PackCardGridProps) {
  if (packs.length === 0) return null;

  return (
    <div className="pack-card-grid">
      {packs.map((pack) => (
        <div key={pack.code ?? pack.title} className="pack-card">
          <div className="pack-card-header">
            <span className="pack-card-emoji">{pack.emoji}</span>
            <h4 className="pack-card-title">{pack.title}</h4>
          </div>
          {pack.description && (
            <p className="pack-card-description">{pack.description}</p>
          )}
          <dl className="pack-card-meta">
            {pack.duration && (
              <>
                <dt>⏱ Durée</dt>
                <dd>{pack.duration}</dd>
              </>
            )}
            {pack.capacity != null && (
              <>
                <dt>👥 Capacité</dt>
                <dd>{pack.capacity} personne(s)</dd>
              </>
            )}
            {pack.audience && (
              <>
                <dt>🎯 Public</dt>
                <dd>{pack.audience}</dd>
              </>
            )}
            {pack.location && (
              <>
                <dt>📍 Lieu</dt>
                <dd>{pack.location}</dd>
              </>
            )}
          </dl>
        </div>
      ))}
    </div>
  );
}