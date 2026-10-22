import { useState } from "react";
import type { MonumentSummary } from "../../types/monument";
import { monumentDisplayName } from "../../types/monument";

interface MonumentThumbProps {
  monument: MonumentSummary;
}

function fallbackInitial(monument: MonumentSummary): string {
  const name = monumentDisplayName(monument).trim();
  return name.length > 0 ? name[0].toUpperCase() : "C";
}

/**
 * Monument thumbnail with a designed fallback.
 * Never renders a broken browser image icon: if the URL is missing or fails to
 * load, a gradient placeholder with the monument initial is shown instead.
 */
export default function MonumentThumb({ monument }: MonumentThumbProps) {
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(monument.image_url) && !failed;

  return (
    <div className="monument-thumb" aria-hidden="true">
      {showImage ? (
        <img
          src={monument.image_url as string}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
        />
      ) : (
        <div className="monument-thumb-fallback">{fallbackInitial(monument)}</div>
      )}
    </div>
  );
}
