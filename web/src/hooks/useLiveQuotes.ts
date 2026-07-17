"use client";

import { useEffect, useState } from "react";
import { Instrument, MarketSnapshot } from "@/lib/types";

const POLL_MS = 5 * 60 * 1000;

type QuotesPayload = {
  as_of: string;
  prices: Record<string, number | null>;
};

export function useLiveQuotes(initialMarket: MarketSnapshot) {
  const [asOf, setAsOf] = useState(initialMarket.as_of);
  const [btc, setBtc] = useState(initialMarket.btc_price);
  const [instruments, setInstruments] = useState(initialMarket.instruments);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const res = await fetch("/api/quotes", { cache: "no-store" });
        if (!res.ok) throw new Error(`quotes ${res.status}`);
        const data = (await res.json()) as QuotesPayload;
        if (cancelled) return;

        setAsOf(data.as_of);
        if (data.prices.BTC != null) setBtc(data.prices.BTC);
        setInstruments((prev) =>
          prev.map((inst: Instrument) => {
            const px = data.prices[inst.ticker];
            if (px == null) return inst;
            return { ...inst, market_price: px, price_source: "yahoo_live" };
          })
        );
        setLive(true);
        setError(null);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "quote refresh failed");
        }
      }
    }

    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return { asOf, btc, instruments, live, error };
}
