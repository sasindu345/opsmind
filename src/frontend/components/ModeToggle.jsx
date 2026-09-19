import React from "react";

export function ModeToggle({ mode, onToggle }) {
  const isBeginner = mode === "beginner";

  return (
    <div className="mode-toggle-container" title={`Current: ${isBeginner ? "Beginner Mode (Simplified, Plain-English)" : "Engineer Mode (Full Diagnostic & Raw Telemetry)"}`}>
      <button
        type="button"
        className={`mode-btn ${isBeginner ? "active" : ""}`}
        onClick={() => onToggle("beginner")}
        aria-pressed={isBeginner}
      >
        <span className="mode-icon">🌱</span>
        <span className="mode-label">Beginner</span>
      </button>
      <button
        type="button"
        className={`mode-btn ${!isBeginner ? "active" : ""}`}
        onClick={() => onToggle("engineer")}
        aria-pressed={!isBeginner}
      >
        <span className="mode-icon">⚡</span>
        <span className="mode-label">Engineer</span>
      </button>
    </div>
  );
}
