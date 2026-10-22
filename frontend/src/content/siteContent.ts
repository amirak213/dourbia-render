export type SiteView = "home" | "explorer" | "circuit" | "sessions" | "about";

export const SITE_CONTACT = {
  website: "https://www.dourbia.tn",
  email: "contact@dourbia.tn",
  tagline: "Your cultural experiences — in one click",
  taglineFr: "Vos expériences culturelles en un clic",
} as const;

export const HOME_PRODUCT_CARDS = [
  {
    title: "Guide historique sourcé",
    description:
      "Réponses contextualisées avec citations vérifiables à partir des données patrimoniales de Carthage.",
  },
  {
    title: "Circuits personnalisés",
    description:
      "Itinéraires optimisés selon votre temps, budget, mobilité et préférences historiques.",
  },
  {
    title: "Carte interactive",
    description:
      "Explorez les monuments de Carthage sur une carte et connectez-les au guide historique.",
  },
] as const;

export const AGENT_PERSONALIZATION_CHIPS = [
  "Langue",
  "Intérêt historique",
  "Durée disponible",
  "Monument mentionné",
  "Recherche web",
] as const;

export const TOURS_FEATURES = [
  {
    title: "Circuits de visite",
    description: "Itinéraires optimisés selon durée, mobilité, budget et préférences.",
  },
  {
    title: "Guide digital personnalisé",
    description: "IA entraînée sur les données touristiques pour une visite sur mesure.",
  },
  {
    title: "Contenu multimédia",
    description: "Texte, audio, vidéo et expériences 3D autour du patrimoine.",
  },
  {
    title: "Packs de services locaux",
    description: "Restaurants, artisans, hôtels et activités culturelles connectés.",
  },
] as const;

export const PERSONALIZATION_FACTORS = [
  "Durée",
  "Mobilité",
  "Transport",
  "Services",
  "Budget",
] as const;

export const ABOUT_MISSION =
  "Rendre le patrimoine culturel et les services locaux accessibles à chaque touriste grâce à des outils numériques intelligents. Nous aidons les visiteurs à découvrir des expériences authentiques tout en soutenant les communautés locales et un tourisme durable.";

export const SUSTAINABILITY_PILLARS = [
  {
    title: "Aspect social",
    description:
      "Inclusion des communautés locales : restaurants, hôtels, commerces et artisans.",
  },
  {
    title: "Aspect économique",
    description:
      "Valorisation des sites patrimoniaux et génération de revenus pour le secteur culturel.",
  },
  {
    title: "Aspect environnemental",
    description:
      "Réduction de l'impact par la digitalisation et encouragement des modes de transport durables.",
  },
] as const;

export const PROBLEM_POINTS = [
  "9M+ arrivées touristiques par an en Tunisie (ONTT 2025).",
  "0 chatbot touristique IA dédié en Tunisie aujourd'hui.",
  "Applications existantes statiques et peu personnalisées.",
  "Pas de guidance conversationnelle multilingue unifiée.",
  "Pas de moteur d'optimisation de circuits en temps réel.",
] as const;

export const STRENGTHS = [
  {
    title: "Multilingue",
    detail: "FR · EN · AR · IT — dialogue naturel et code-switching.",
  },
  {
    title: "Connaissance historique",
    detail: "RAG sur monuments, culture et patrimoine tunisien.",
  },
  {
    title: "Optimisation de circuits",
    detail: "Algorithmes et scoring selon temps, budget et préférences.",
  },
] as const;

export const TEAM = [
  { name: "Dr. Ines Hassoumi", role: "CEO — Informaticienne, IA" },
  { name: "Dr. Alia Belkaid", role: "CTO — R&D Manager" },
  { name: "Tejeddine Bdira Filali", role: "Ingénieur géomaticien et géomètre" },
  { name: "Hamdi Sansa", role: "Ingénieur IT" },
  { name: "Wiem Hammouda", role: "Data scientist" },
  { name: "Sofia Ouertani", role: "Coach" },
  { name: "Azzedine Beshaouech", role: "Historien et archéologue" },
  { name: "Malek Manai", role: "AI Intern" },
  { name: "Hamza Zighni", role: "AI Intern" },
  { name: "Amira Koumenji", role: "AI & Data Intern" },
] as const;

export const HELP_ITEMS = [
  {
    question: "Comment utiliser le guide ?",
    answer:
      "Posez une question en français, anglais ou arabe. Le guide répond dans la langue de votre message.",
  },
  {
    question: "Quels sujets sont couverts ?",
    answer:
      "Monuments et circuits de Carthage, histoire punique et romaine, horaires et suggestions de visite.",
  },
  {
    question: "Les réponses sont-elles fiables ?",
    answer:
      "Le guide s'appuie sur une base documentaire locale (RAG) et peut compléter avec une recherche web quand c'est pertinent.",
  },
  {
    question: "Puis-je demander un circuit ?",
    answer:
      "Oui — précisez votre temps disponible, vos intérêts (romain, punique…) et le guide adaptera ses suggestions.",
  },
] as const;
