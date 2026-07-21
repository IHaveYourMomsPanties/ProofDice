import React from "react";

/**
 * Big 7-segment style digital display.
 * Shows a "ghost" background of all-off "88.88" segments, and overlays the
 * actual roll value on top, coloured for win / loss / rolling / idle.
 */
export default function DigitalDisplay({ value, state = "idle" }) {
  // Format value to always be XX.XX
  const num = typeof value === "number" ? value : parseFloat(value ?? 0);
  const clamped = Math.max(0, Math.min(99.99, isNaN(num) ? 0 : num));
  const [intPart, decPart] = clamped.toFixed(2).split(".");
  const padded = `${intPart.padStart(2, "0")}.${decPart}`;

  return (
    <div className="sd-dice-display" data-testid="dice-display">
      <div className="sd-dice-digit-wrap">
        {/* off segments - "88.88" */}
        <div className="sd-dice-off select-none" aria-hidden="true">
          88.88
        </div>
        {/* on layer */}
        <div className={`sd-dice-on ${state}`} data-testid="dice-value">
          {padded}
        </div>
      </div>
      {state === "win" && (
        <div
          className="absolute top-3 right-4 rounded-full px-3 py-1 text-xs font-black tracking-widest"
          style={{ background: "rgba(123,193,66,0.20)", color: "#4d8b25" }}
          data-testid="win-badge"
        >
          WIN
        </div>
      )}
      {state === "loss" && (
        <div
          className="absolute top-3 right-4 rounded-full px-3 py-1 text-xs font-black tracking-widest"
          style={{ background: "rgba(225,74,56,0.18)", color: "#b23628" }}
          data-testid="loss-badge"
        >
          LOSS
        </div>
      )}
    </div>
  );
}
