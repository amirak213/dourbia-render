import { useState } from "react";
import { DEBUG_MEMORY } from "../config";
import type { Message, WizardAction } from "../types";
import SourceList from "./SourceList";
import WizardRenderer from "./chat/wizard/WizardRenderer";
import PackCardGrid from "./PackCardGrid";

interface MessageBubbleProps {
  message: Message;
  onSuggestedActionClick?: (text: string) => void;
  isLatest?: boolean;
  onWizardAnswer?: (action: WizardAction, label: string) => void;
}

function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  return `${(ms / 1000).toFixed(1)} s`;
}

function formatLatencyStep(value: number | null | undefined): string {
  if (value == null) {
    return "n/a";
  }
  return formatDuration(value);
}

export default function MessageBubble({
  message,
  onSuggestedActionClick,
  isLatest = false,
  onWizardAnswer,
}: MessageBubbleProps) {
  const [showDebug, setShowDebug] = useState(false);
  const isUser = message.role === "user";
  const hasSources = Boolean(message.sources && message.sources.length > 0);
  const hasMemory = Boolean(message.memory);
  const hasLatencyDebug = Boolean(message.latencyDebug);
  const showDebugToggle =
    DEBUG_MEMORY && !isUser && (hasMemory || hasLatencyDebug);

  return (
    <article className={`message-row ${isUser ? "user" : "assistant"}`}>
      {!isUser && (
        <img src="/dourbia-icon.png" alt="" className="message-avatar-img" />
      )}
      <div className="message-body">
        <div className="message-content">
          {message.content.split("\n").map((line, index) => (
            <p key={index}>{line}</p>
          ))}
        </div>

        {!isUser && message.actions && message.actions.length > 0 && (
          <div className="message-actions">
            {message.actions.map((action) => (
              <button
                key={action}
                type="button"
                className="action-chip"
                onClick={() => onSuggestedActionClick?.(action)}
              >
                {action}
              </button>
            ))}
          </div>
        )}

        {!isUser && message.wizard && (
          <WizardRenderer
            wizard={message.wizard}
            interactive={isLatest}
            onAnswer={(action, label) => onWizardAnswer?.(action, label)}
          />
        )}

        {!isUser && message.packs && message.packs.length > 0 && (
          <PackCardGrid packs={message.packs} />
        )}

        {!isUser && hasSources && <SourceList sources={message.sources!} />}

        {showDebugToggle && (
          <div className="message-details">
            <button
              type="button"
              className="details-toggle"
              onClick={() => setShowDebug((value) => !value)}
              aria-expanded={showDebug}
            >
              {showDebug ? "Masquer le contexte" : "Contexte utilisé"}
            </button>
            {showDebug && (
              <div className="details-panel">
                {hasLatencyDebug && (
                  <section>
                    <h4>Latence (debug)</h4>
                    <dl className="memory-grid latency-grid">
                      <dt>Mémoire (lecture)</dt>
                      <dd>
                        {formatLatencyStep(message.latencyDebug!.memory_retrieval_ms)}
                      </dd>
                      <dt>Retrieval</dt>
                      <dd>{formatLatencyStep(message.latencyDebug!.retrieval_ms)}</dd>
                      <dt>Prompt</dt>
                      <dd>
                        {formatLatencyStep(message.latencyDebug!.prompt_construction_ms)}
                      </dd>
                      <dt>LLM</dt>
                      <dd>
                        {formatLatencyStep(message.latencyDebug!.llm_generation_ms)}
                      </dd>
                      <dt>Mémoire (écriture)</dt>
                      <dd>
                        {formatLatencyStep(message.latencyDebug!.memory_update_ms)}
                      </dd>
                      <dt>Web search</dt>
                      <dd>{formatLatencyStep(message.latencyDebug!.web_search_ms)}</dd>
                    </dl>
                  </section>
                )}
                {hasMemory && (
                  <section
                    className={hasLatencyDebug ? "details-section-spaced" : undefined}
                  >
                    <h4>Mémoire de session</h4>
                    <dl className="memory-grid">
                      <dt>Langue</dt>
                      <dd>{message.memory!.preferred_language}</dd>
                      {message.memory!.interests.length > 0 && (
                        <>
                          <dt>Intérêts</dt>
                          <dd>{message.memory!.interests.join(", ")}</dd>
                        </>
                      )}
                    </dl>
                  </section>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </article>
  );
}
