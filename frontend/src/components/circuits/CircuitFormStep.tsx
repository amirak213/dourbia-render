import type { ReactNode } from "react";

interface CircuitFormStepProps {
  step: number;
  totalSteps: number;
  title: string;
  children: ReactNode;
}

export default function CircuitFormStep({
  step,
  totalSteps,
  title,
  children,
}: CircuitFormStepProps) {
  const progress = (step / totalSteps) * 100;

  return (
    <div className="circuit-form-step">
      <div className="circuit-form-progress" aria-label={`Étape ${step} sur ${totalSteps}`}>
        <div className="circuit-form-progress-label">
          <span>Étape {step} / {totalSteps}</span>
        </div>
        <div className="circuit-form-progress-bar">
          <div
            className="circuit-form-progress-fill"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
      <h3 className="circuit-form-step-title">{title}</h3>
      {children}
    </div>
  );
}
