export type TariffType =
  | "resident"
  | "etudiant"
  | "etranger"
  | "enseignant"
  | "retraite"
  | "enfant";

export type TransportMode =
  | "walking"
  | "bike"
  | "car"
  | "public_transport";

export type MobilityLevel = "normale" | "reduite" | "limitee";

export interface CircuitPreferences {
  epoques: string[];
  fonctions: string[];
  must_visit: string[];
  avoid: string[];
}

export interface CircuitRecommendRequest {
  session_id: string;
  age?: number | null;
  type_tarif: TariffType;
  budget_max: number;
  transport: TransportMode;
  mobilite: MobilityLevel;
  duration_minutes?: number | null;
  start_time?: string | null;
  end_time?: string | null;
  zone: string;
  preferences: CircuitPreferences;
  start_location?: string | null;
  end_location?: string | null;
  max_stops?: number;
}

export interface RecommendedMonument {
  order: number;
  monument_id?: number | null;
  name: string;
  latitude: number;
  longitude: number;
  visit_duration_min: number;
  price: number | null;
  arrival_time?: string | null;
  departure_time?: string | null;
  reason: string;
}

export interface CircuitSummary {
  title: string;
  summary: string;
  monuments: RecommendedMonument[];
  total_visit_duration_min: number;
  total_travel_duration_min: number;
  total_duration_min: number;
  total_distance_km: number;
  total_price: number;
  unknown_price_count: number;
  budget_max?: number | null;
  score: number;
}

export interface RouteSegment {
  from: string;
  to: string;
  distance_km: number;
  duration_min: number;
  path: [number, number][];
}

export interface MapRoutePayload {
  transport: string;
  polyline: [number, number][];
  segments: RouteSegment[];
}

export interface CircuitConstraintsStatus {
  budget_ok: boolean;
  duration_ok: boolean;
  mobility_ok: boolean;
}

export interface CircuitRecommendResponse {
  session_id: string;
  circuit: CircuitSummary;
  route: MapRoutePayload;
  constraints: CircuitConstraintsStatus;
  explanation: string[];
  alternatives: CircuitSummary[];
  warnings: string[];
  feasible: boolean;
}

export interface CircuitFormState {
  type_tarif: TariffType;
  budget_max: string;
  transport: TransportMode;
  mobilite: MobilityLevel;
  duration_minutes: string;
  start_time: string;
  end_time: string;
  epoques: string[];
  fonctions: string[];
  must_visit: string[];
}
