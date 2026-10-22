export const PERIOD_OPTIONS = [
  "Romaine",
  "Punique",
  "Byzantine",
  "Coloniale",
] as const;

export const FUNCTION_OPTIONS = [
  "musee",
  "religieux",
  "culturel",
  "habitation",
] as const;

export const FUNCTION_LABELS: Record<(typeof FUNCTION_OPTIONS)[number], string> = {
  musee: "Musée",
  religieux: "Religieux",
  culturel: "Culturel",
  habitation: "Habitation",
};

export const TARIF_LABELS: Record<string, string> = {
  etudiant: "Étudiant",
  resident: "Résident",
  etranger: "Étranger",
  enseignant: "Enseignant",
  retraite: "Retraité",
  enfant: "Enfant",
};

export const MOBILITE_LABELS: Record<string, string> = {
  normale: "Normale",
  reduite: "Réduite",
  limitee: "Limitée",
};

export const TRANSPORT_LABELS: Record<string, string> = {
  walking: "À pied",
  bike: "Vélo",
  car: "Voiture",
  public_transport: "Transport public",
};

/** Primary monuments shown by default in the form. */
export const FEATURED_MONUMENT_OPTIONS = [
  "Thermes d'Antonin",
  "Theatre",
  "Tophet",
  "Ports puniques",
  "La colline de Byrsa",
  "Musée national de Carthage",
  "Quartier Magon",
] as const;

/** Additional monuments revealed via “Voir plus”. */
export const EXTRA_MONUMENT_OPTIONS = [
  "Parc des villas romaines",
  "Amphithéâtre de Carthage",
  "Odéon",
  "Musée Océanographique (Dar El Hout)",
  "Beit El Hikma",
  "Maison de Dionysos",
] as const;

export const CIRCUIT_FORM_STEPS = [
  { id: 1, title: "Votre profil" },
  { id: 2, title: "Votre temps" },
  { id: 3, title: "Vos préférences" },
  { id: 4, title: "Monuments souhaités" },
] as const;

export const DEFAULT_CIRCUIT_FORM = {
  type_tarif: "etudiant" as const,
  budget_max: "30",
  transport: "walking" as const,
  mobilite: "normale" as const,
  duration_minutes: "120",
  start_time: "09:00",
  end_time: "11:00",
  epoques: ["Romaine", "Punique"],
  fonctions: ["musee", "culturel"],
  must_visit: ["Thermes d'Antonin"] as string[],
};
