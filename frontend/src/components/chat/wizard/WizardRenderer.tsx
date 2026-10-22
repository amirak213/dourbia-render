import type { WizardOption, WizardUI } from "../../../types";
import Card from "../../ui/Card";
import { buildWizardAction } from "./wizardEvents";
import SingleSelectCards from "./SingleSelectCards";
import PlaceMultiSelect from "./PlaceMultiSelect";
import BudgetForm from "./BudgetForm";
import MobilityForm from "./MobilityForm";
import TimeForm from "./TimeForm";
import PreferencesForm from "./PreferencesForm";
import ConfirmCard from "./ConfirmCard";

interface WizardRendererProps {
  wizard: WizardUI;
  /** false une fois que cette card n'est plus le dernier message (déjà répondue) */
  interactive: boolean;
  /** action structurée + libellé lisible à afficher comme "message utilisateur" */
  onAnswer: (action: ReturnType<typeof buildWizardAction>, label: string) => void | Promise<void>;
}

export default function WizardRenderer({ wizard, interactive, onAnswer }: WizardRendererProps) {
  function submitOption(option: WizardOption) {
    return onAnswer(buildWizardAction(wizard.state, option.value), option.label);
  }

  function submitPlaces(options: WizardOption[]) {
    return onAnswer(
      buildWizardAction(
        wizard.state,
        options.map((option) => option.value),
      ),
      options.map((option) => option.label).join(", "),
    );
  }

  function submitLoadMore() {
    return onAnswer(buildWizardAction(wizard.state, "load_more"), "Voir plus");
  }

  function submitStructured(value: Record<string, unknown>, label: string) {
    return onAnswer(buildWizardAction(wizard.state, value), label);
  }

  return (
    <Card compact className="wizard-card">
      {wizard.input_type === "single_select" && (
        <SingleSelectCards
          options={wizard.options}
          interactive={interactive}
          onSelect={submitOption}
        />
      )}

      {wizard.input_type === "multi_select" && (
        <PlaceMultiSelect
          options={wizard.options}
          hasMore={wizard.has_more}
          interactive={interactive}
          onSubmit={submitPlaces}
          onLoadMore={submitLoadMore}
        />
      )}

      {wizard.input_type === "budget_form" && (
        <BudgetForm
          options={wizard.options}
          interactive={interactive}
          onSubmit={submitStructured}
        />
      )}

      {wizard.input_type === "mobility_form" && (
        <MobilityForm
          options={wizard.options}
          interactive={interactive}
          onSubmit={submitStructured}
        />
      )}

      {wizard.input_type === "time_form" && (
        <TimeForm interactive={interactive} onSubmit={submitStructured} />
      )}

      {wizard.input_type === "preferences_form" && (
        <PreferencesForm
          options={wizard.options}
          interactive={interactive}
          onSubmit={submitStructured}
        />
      )}

      {wizard.input_type === "confirm" && (
        <ConfirmCard
          options={wizard.options}
          budgetOk={wizard.budget_ok}
          budgetWarning={wizard.budget_warning}
          circuit={wizard.circuit}
          interactive={interactive}
          onSelect={submitOption}
        />
      )}
    </Card>
  );
}
