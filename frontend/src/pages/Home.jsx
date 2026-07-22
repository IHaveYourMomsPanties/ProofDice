import React, { useState } from "react";
import Header from "@/components/Header";
import DiceGame from "@/components/DiceGame";
import BetsTable from "@/components/BetsTable";
import ChatSidebar from "@/components/ChatSidebar";
import ProvablyFair from "@/components/ProvablyFair";
import ComplianceBanner from "@/components/ComplianceBanner";
import { useAuth } from "@/context/AuthContext";
import { Link } from "react-router-dom";

export default function HomePage() {
  const { user, loading } = useAuth();
  const [activeCoin, setActiveCoin] = useState("BTC");
  const [latestBetId, setLatestBetId] = useState(null);

  return (
    <div className="min-h-screen" data-testid="home-page">
      <Header activeCoin={activeCoin} setActiveCoin={setActiveCoin} />

      <main className="max-w-[1400px] mx-auto px-3 md:px-8 py-4 md:py-8">
        <ComplianceBanner />

        {/* Marketing banner when logged out */}
        {!user && !loading && (
          <div
            className="rounded-3xl mb-6 p-5 md:p-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-4"
            style={{
              background:
                "linear-gradient(135deg, #0fa968 0%, #075532 55%, #ff6b57 130%)",
              color: "white",
            }}
            data-testid="hero-banner"
          >
            <div>
              <div className="text-xs font-black tracking-[0.3em] opacity-80">
                CRYPTO DICE · PROVABLY FAIR
              </div>
              <h1 className="text-3xl md:text-5xl font-black mt-1 leading-tight">
                Roll fast. Roll fair. <span className="opacity-80">Roll BetterDice.</span>
              </h1>
              <p className="mt-2 text-sm md:text-base opacity-85 max-w-lg">
                Real-crypto provably-fair dice on the big three EVM chains —
                Ethereum, BNB Chain, and Polygon — plus BTC, Solana and TON.
                1% house edge. Deposit straight from your wallet and start rolling.
              </p>
            </div>
            <div className="flex gap-3">
              <Link
                to="/register"
                data-testid="hero-signup"
                className="bg-white text-[color:var(--sd-purple-deep)] font-black tracking-widest px-6 py-3 rounded-full hover:bg-white/90 text-sm"
              >
                CREATE ACCOUNT
              </Link>
              <Link
                to="/login"
                data-testid="hero-login"
                className="bg-white/15 hover:bg-white/25 text-white font-black tracking-widest px-6 py-3 rounded-full text-sm"
              >
                LOG IN
              </Link>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          <section className="lg:col-span-8 xl:col-span-9">
            <DiceGame
              activeCoin={activeCoin}
              onNewBet={(b) => setLatestBetId(b.id)}
            />
            <ProvablyFair />
            <BetsTable latestBetId={latestBetId} />
          </section>

          <section className="lg:col-span-4 xl:col-span-3">
            <div className="lg:sticky lg:top-20">
              <ChatSidebar />
            </div>
          </section>
        </div>

        <footer className="mt-10 text-center text-xs text-muted-foreground pb-8">
          BetterDice.io · Play-money demo · Provably fair
        </footer>
      </main>
    </div>
  );
}
