import React, { useEffect, useState } from "react";
import { ShieldAlert, X } from "lucide-react";

const KEY = "bd_compliance_ack_v1";

export default function ComplianceBanner() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!window.localStorage.getItem(KEY)) {
      setVisible(true);
    }
  }, []);

  if (!visible) return null;

  const ack = () => {
    window.localStorage.setItem(KEY, new Date().toISOString());
    setVisible(false);
  };

  return (
    <div
      className="rounded-2xl mb-6 p-4 md:p-5 flex items-start md:items-center gap-4 border-2"
      style={{
        background: "#fff4de",
        borderColor: "#e6b800",
        color: "#5a4400",
      }}
      data-testid="compliance-banner"
    >
      <ShieldAlert className="w-6 h-6 md:w-7 md:h-7 shrink-0 mt-0.5 md:mt-0" style={{ color: "#a37b00" }} />
      <div className="flex-1 text-sm md:text-[15px] leading-snug">
        <b className="tracking-wide">Play responsibly. Follow your local laws.</b>{" "}
        BetterDice is a real-crypto game of chance. You are solely responsible
        for ensuring that online gambling is legal in your state, province, or
        country before playing. If gambling is causing you harm, seek help
        (e.g. <a
          className="underline font-bold"
          href="https://www.ncpgambling.org/help-treatment/"
          target="_blank"
          rel="noopener noreferrer"
        >NCPG</a>).
      </div>
      <button
        onClick={ack}
        data-testid="compliance-ack"
        className="rounded-full px-4 py-2 text-xs font-black tracking-widest bg-[#a37b00] hover:bg-[#8a6800] text-white shrink-0"
      >
        I UNDERSTAND
      </button>
      <button
        onClick={ack}
        className="p-1 rounded-full hover:bg-black/10 shrink-0"
        aria-label="dismiss"
        data-testid="compliance-close"
      >
        <X className="w-4 h-4" style={{ color: "#5a4400" }} />
      </button>
    </div>
  );
}
