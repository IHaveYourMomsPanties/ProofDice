import React from "react";

/**
 * Recent rolls history strip: 7 pill badges in 7-seg font, coloured win/loss.
 */
export default function RollHistory({ rolls }) {
  const items = (rolls || []).slice(0, 7);
  while (items.length < 7) items.push(null);

  return (
    <div className="flex gap-2 overflow-x-auto pb-1" data-testid="roll-history">
      {items.map((r, i) => {
        if (!r) {
          return (
            <div
              key={`empty-${i}`}
              className="sd-roll-badge"
              style={{ background: "rgba(107,95,190,0.06)", color: "rgba(107,95,190,0.35)" }}
            >
              88.88
            </div>
          );
        }
        return (
          <div
            key={r.id}
            className={`sd-roll-badge ${r.won ? "win" : "loss"}`}
            data-testid={`roll-history-item-${i}`}
          >
            {r.roll.toFixed(2)}
          </div>
        );
      })}
    </div>
  );
}
