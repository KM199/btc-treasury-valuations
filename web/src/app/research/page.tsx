import Link from "next/link";
import fair from "../../../public/data/fair_values.json";
import { formatUsd } from "@/lib/types";

export default function ResearchPage() {
  const sata = fair.tickers.find((t) => t.ticker === "SATA");
  const dist = sata?.npv_distribution;

  return (
    <article className="mx-auto max-w-3xl px-5 py-16 md:px-8">
      <p className="font-mono text-xs uppercase tracking-[0.28em] text-ember-400">
        Research
      </p>
      <h1 className="mt-4 font-display text-4xl text-mist-100 md:text-5xl">
        What we assume — and what we don&apos;t
      </h1>
      <p className="mt-6 text-lg text-mist-300">
        This project is a portfolio of models: dividend Monte Carlo for
        preferreds, capital-structure wipeout math for Strategy, and options
        hedges that put a floor under price risk. The site surfaces the
        numbers; the underlying research lives in the methodology and capital
        stack pages.
      </p>

      {dist ? (
        <div className="mt-12 grid gap-4 sm:grid-cols-3">
          <div className="border border-white/8 bg-ink-900/60 p-4">
            <p className="text-xs uppercase tracking-wider text-mist-500">SATA mean NPV</p>
            <p className="mt-2 font-mono text-2xl text-ember-400">
              {formatUsd(dist.mean ?? dist.final_per_share)}
            </p>
          </div>
          <div className="border border-white/8 bg-ink-900/60 p-4">
            <p className="text-xs uppercase tracking-wider text-mist-500">Median</p>
            <p className="mt-2 font-mono text-2xl text-mist-100">
              {formatUsd(dist.median)}
            </p>
          </div>
          <div className="border border-white/8 bg-ink-900/60 p-4">
            <p className="text-xs uppercase tracking-wider text-mist-500">Vs par</p>
            <p className="mt-2 font-mono text-2xl text-mist-100">
              {dist.vs_par != null ? `${dist.vs_par.toFixed(1)}%` : "—"}
            </p>
          </div>
        </div>
      ) : null}

      <h2 className="mt-14 font-display text-2xl text-mist-100">Limitations</h2>
      <ul className="mt-4 list-disc space-y-2 pl-5 text-mist-300">
        <li>Market data is delayed / scheduled — not a broker tick feed.</li>
        <li>Dividend policy can change; the model encodes rules, not promises.</li>
        <li>Preferreds are not collateralized by Bitcoin.</li>
        <li>STRC fair value lands when the shared engine job finishes; until then the UI shows market only.</li>
      </ul>

      <h2 className="mt-14 font-display text-2xl text-mist-100">Go deeper</h2>
      <ul className="mt-4 space-y-2 text-mist-300">
        <li>
          <Link href="/methodology" className="text-ember-400 hover:underline">
            Methodology
          </Link>{" "}
          — how paths become fair value
        </li>
        <li>
          <Link href="/capital-structure" className="text-ember-400 hover:underline">
            Capital stack
          </Link>{" "}
          — senior claims and wipeout bands
        </li>
        <li>
          <Link href="/preferreds" className="text-ember-400 hover:underline">
            Preferreds
          </Link>{" "}
          — get-even, baseline, hedges
        </li>
      </ul>

      <p className="mt-12">
        <Link href="/" className="text-ember-400 hover:underline">
          ← Back to values
        </Link>
      </p>
    </article>
  );
}
