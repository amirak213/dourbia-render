import { useState } from "react";
import Button from "../../ui/Button";

interface TimeFormProps {
  interactive: boolean;
  onSubmit: (
    value: { duration_minutes: number; start_time: string; end_time: string },
    label: string,
  ) => void;
}

export default function TimeForm({ interactive, onSubmit }: TimeFormProps) {
  const [duration, setDuration] = useState("120");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("12:00");
  const durationMinutes = Number(duration);
  const canSubmit =
    Number.isInteger(durationMinutes) &&
    durationMinutes >= 15 &&
    durationMinutes <= 720 &&
    Boolean(startTime) &&
    Boolean(endTime) &&
    startTime < endTime;

  function handleSubmit() {
    if (!interactive || !canSubmit) return;
    onSubmit(
      { duration_minutes: durationMinutes, start_time: startTime, end_time: endTime },
      `${durationMinutes} min · ${startTime} - ${endTime}`,
    );
  }

  return (
    <div className={`wizard-form${interactive ? "" : " wizard-disabled"}`}>
      <div className="wizard-form-row">
        <label className="wizard-field">
          <span>Durée (minutes)</span>
          <input
            type="number"
            min={15}
            max={720}
            step={1}
            className="wizard-input"
            value={duration}
            disabled={!interactive}
            onChange={(event) => setDuration(event.target.value)}
          />
        </label>
        <label className="wizard-field">
          <span>Heure de début</span>
          <input
            type="time"
            className="wizard-input"
            value={startTime}
            disabled={!interactive}
            onChange={(event) => setStartTime(event.target.value)}
          />
        </label>
        <label className="wizard-field">
          <span>Heure de fin</span>
          <input
            type="time"
            className="wizard-input"
            value={endTime}
            disabled={!interactive}
            onChange={(event) => setEndTime(event.target.value)}
          />
        </label>
      </div>
      {interactive && (
        <Button variant="primary" compact onClick={handleSubmit} disabled={!canSubmit}>
          Valider
        </Button>
      )}
    </div>
  );
}