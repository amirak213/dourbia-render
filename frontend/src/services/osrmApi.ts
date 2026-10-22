export interface OsrmCoordinate {
  latitude: number;
  longitude: number;
}

const OSRM_ENABLED = import.meta.env.VITE_OSRM_ENABLED !== "false";
const OSRM_BASE_URL =
  import.meta.env.VITE_OSRM_BASE_URL ?? "https://router.project-osrm.org";
const OSRM_DEFAULT_PROFILE =
  import.meta.env.VITE_OSRM_PROFILE ?? "driving";

function mapTransportToProfile(transport: string): string {
  switch (transport) {
    case "walking":
      return "walking";
    case "bike":
      return "cycling";
    case "car":
      return "driving";
    case "public_transport":
      return OSRM_DEFAULT_PROFILE;
    default:
      return OSRM_DEFAULT_PROFILE;
  }
}

async function fetchOsrmProfileRoute(
  coordinates: OsrmCoordinate[],
  profile: string,
): Promise<[number, number][]> {
  const path = coordinates
    .map((point) => `${point.longitude},${point.latitude}`)
    .join(";");
  const url = `${OSRM_BASE_URL}/route/v1/${profile}/${path}?overview=full&geometries=geojson`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`OSRM HTTP ${response.status}`);
  }

  const payload = (await response.json()) as {
    code?: string;
    routes?: Array<{
      geometry?: { coordinates?: [number, number][] };
    }>;
  };

  if (payload.code !== "Ok") {
    throw new Error(`OSRM code ${payload.code ?? "unknown"}`);
  }

  const geoCoordinates = payload.routes?.[0]?.geometry?.coordinates;
  if (!geoCoordinates?.length) {
    throw new Error("OSRM returned empty geometry");
  }

  return geoCoordinates.map(([lng, lat]) => [lat, lng] as [number, number]);
}

/**
 * Fetch road-following geometry from OSRM.
 * Tries transport-specific profile, then configured default, then driving.
 */
export async function getOsrmRoute(
  coordinates: OsrmCoordinate[],
  transport: string,
): Promise<[number, number][]> {
  if (!OSRM_ENABLED) {
    throw new Error("OSRM disabled");
  }
  if (coordinates.length < 2) {
    throw new Error("At least two coordinates required");
  }

  const profiles = [
    mapTransportToProfile(transport),
    OSRM_DEFAULT_PROFILE,
    "driving",
  ].filter((profile, index, list) => list.indexOf(profile) === index);

  let lastError: unknown = null;
  for (const profile of profiles) {
    try {
      return await fetchOsrmProfileRoute(coordinates, profile);
    } catch (error) {
      lastError = error;
      if (import.meta.env.DEV) {
        console.warn(`[OSRM] profile "${profile}" failed`, error);
      }
    }
  }

  throw lastError instanceof Error ? lastError : new Error("OSRM route failed");
}

export function isOsrmEnabled(): boolean {
  return OSRM_ENABLED;
}
