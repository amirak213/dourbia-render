export interface MonumentSummary {
  id: number;
  name_fr: string;
  name_en: string | null;
  name_ar: string | null;
  latitude: number;
  longitude: number;
  visit_duration_min: number | null;
  dominant_period: string | null;
  function: string | null;
  popularity: number | null;
  image_url: string | null;
}

export interface MonumentsListResponse {
  monuments: MonumentSummary[];
}

export function monumentDisplayName(
  monument: MonumentSummary,
  language: "fr" | "en" | "ar" = "fr",
): string {
  if (language === "en" && monument.name_en) return monument.name_en;
  if (language === "ar" && monument.name_ar) return monument.name_ar;
  return monument.name_fr;
}
