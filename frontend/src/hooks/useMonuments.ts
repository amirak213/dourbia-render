import { useCallback, useEffect, useState } from "react";
import { fetchMonuments } from "../services/monumentsApi";
import type { MonumentSummary } from "../types/monument";

export function useMonuments() {
  const [monuments, setMonuments] = useState<MonumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const refetch = useCallback(() => {
    setReloadKey((key) => key + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchMonuments()
      .then((items) => {
        if (!cancelled) {
          setMonuments(items);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Impossible de charger les monuments.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return { monuments, loading, error, refetch };
}
