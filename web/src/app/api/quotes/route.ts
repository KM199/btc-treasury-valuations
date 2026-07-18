import { NextResponse } from "next/server";

const SYMBOLS = ["MSTR", "STRC", "ASST", "SATA", "BTC-USD"] as const;

async function yahooLast(symbol: string): Promise<number | null> {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1m&range=1d`;
  try {
    const res = await fetch(url, {
      headers: {
        "User-Agent": "Mozilla/5.0 (compatible; HEDGD/1.0)",
        Accept: "application/json",
      },
      // Always revalidate quotes — this is the live path
      cache: "no-store",
    });
    if (!res.ok) return null;
    const data = await res.json();
    const meta = data?.chart?.result?.[0]?.meta;
    const price =
      meta?.regularMarketPrice ??
      meta?.postMarketPrice ??
      meta?.previousClose ??
      null;
    return typeof price === "number" && Number.isFinite(price) ? price : null;
  } catch {
    // A transient network/parse failure for one symbol must not fail the whole
    // batch — GET() awaits all symbols via Promise.all.
    return null;
  }
}

export async function GET() {
  const entries = await Promise.all(
    SYMBOLS.map(async (symbol) => [symbol, await yahooLast(symbol)] as const)
  );
  const prices: Record<string, number | null> = {};
  for (const [symbol, price] of entries) {
    const key = symbol === "BTC-USD" ? "BTC" : symbol;
    prices[key] = price;
  }
  return NextResponse.json({
    as_of: new Date().toISOString(),
    prices,
    source: "yahoo",
  });
}
