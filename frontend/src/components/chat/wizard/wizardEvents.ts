import type { WizardAction } from "../../../types";

/**
 * Table de correspondance état → type d'événement attendu par
 * wizard_state_machine.py (HANDLERS). Certains états (CIRCUIT_REVIEW)
 * dérivent le type directement de la valeur de l'option cliquée plutôt
 * que d'une entrée fixe ici — voir buildWizardAction.
 */
const STATE_ACTION_TYPE: Record<string, string> = {
  PLACE_SELECTION: "select_places",
  CUSTOMIZATION_BUDGET: "set_budget",
  CUSTOMIZATION_MOBILITY: "set_mobility",
  CUSTOMIZATION_TIME: "set_time",
  CUSTOMIZATION_PREFERENCES: "set_preferences",
  CIRCUIT_ADJUSTMENT: "adjust_circuit",
  GUIDE_MODE_READY: "confirm_guide_mode",
};

/**
 * CIRCUIT_REVIEW n'a pas un unique type d'événement : chaque bouton
 * (confirm_circuit / adjust_circuit) porte directement son propre type
 * dans option.value, sans valeur additionnelle à transmettre.
 */
const STATES_WITH_SELF_DESCRIBING_OPTIONS = new Set(["CIRCUIT_REVIEW"]);

export function buildWizardAction(
  state: string,
  optionValue: string | string[] | Record<string, unknown>,
): WizardAction {
  if (state === "PLACE_SELECTION" && optionValue === "load_more") {
    return { type: "load_more_places" };
  }
  if (STATES_WITH_SELF_DESCRIBING_OPTIONS.has(state)) {
    return { type: optionValue as string };
  }
  const type = STATE_ACTION_TYPE[state];
  if (!type) {
    throw new Error(`Aucun type d'événement mappé pour l'état wizard "${state}"`);
  }
  return { type, value: optionValue };
}
