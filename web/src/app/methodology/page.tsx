import Link from "next/link";

export default function MethodologyPage() {
  return (
    <article className="mx-auto max-w-3xl px-5 py-16 md:px-8">
      <p className="font-mono text-xs uppercase tracking-[0.28em] text-ember-400">
        Methodology
      </p>
      <h1 className="mt-4 font-display text-4xl text-mist-100 md:text-5xl">
        How we turn Bitcoin paths into a fair value
      </h1>
      <p className="mt-6 text-lg text-mist-300">
        Preferred shares promise dividends. Those dividends only keep coming if the
        company can fund them — usually from cash first, then by selling Bitcoin when
        it is allowed to. We simulate thousands of Bitcoin futures and ask what those
        cash flows are worth today.
      </p>

      <ol className="mt-12 space-y-10">
        <li>
          <h2 className="font-display text-2xl text-mist-100">1. Imagine many Bitcoins</h2>
          <p className="mt-3 text-mist-300">
            We generate monthly Bitcoin price paths for a century using a manually
            tuned return distribution (not a black-box auto-fit). Each path is one
            possible future.
          </p>
        </li>
        <li>
          <h2 className="font-display text-2xl text-mist-100">2. Pay dividends along the way</h2>
          <p className="mt-3 text-mist-300">
            Cash can always pay. Bitcoin sales only happen when holdings marked to
            market clear a suspension threshold (a multiple of par). Missed dividends
            can compound up to a cap. That is the real operating story — not a
            perpetual coupon fantasy.
          </p>
        </li>
        <li>
          <h2 className="font-display text-2xl text-mist-100">3. Discount what actually got paid</h2>
          <p className="mt-3 text-mist-300">
            Paid cash flows are discounted back to today. Average across paths →{" "}
            <strong className="text-mist-100">model fair value per share</strong>.
            Compare that number to the market price. The gap is the thesis.
          </p>
        </li>
      </ol>

      <details className="mt-12 border border-white/10 bg-ink-900/50 p-5">
        <summary className="cursor-pointer font-display text-lg text-mist-100">
          Details for technical readers
        </summary>
        <ul className="mt-4 list-disc space-y-2 pl-5 text-sm text-mist-400">
          <li>
            Valuation engine runs a long-horizon Monte Carlo of dividend cash
            flows under the payment rules above.
          </li>
          <li>
            Bitcoin futures are drawn from a manually tuned monthly return
            distribution, then stored as path matrices for reuse.
          </li>
          <li>
            Analyses: baseline, BTC-start scenarios, suspension-threshold and
            dividend-rate sensitivities.
          </li>
        </ul>
      </details>

      <p className="mt-12 space-x-4">
        <Link href="/preferreds" className="text-ember-400 hover:underline">
          Preferreds comparison →
        </Link>
        <Link href="/commons" className="text-ember-400 hover:underline">
          Commons comparison →
        </Link>
      </p>
    </article>
  );
}
