import Link from "next/link";

const links = [
  { href: "/commons", label: "Commons" },
  { href: "/preferreds", label: "Preferreds" },
  { href: "/capital-structure", label: "Capital stack" },
  { href: "/research", label: "Research" },
];

export function SiteHeader() {
  return (
    <header className="relative z-20 border-b border-white/5 bg-ink-950/70 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-5 py-4 md:px-8">
        <Link href="/" className="group flex items-baseline gap-2">
          <span className="font-display text-xl tracking-tight text-mist-100 md:text-2xl">
            HEDGD
          </span>
        </Link>
        <nav className="flex flex-wrap items-center justify-end gap-x-5 gap-y-2 text-sm text-mist-300">
          {links.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className="transition-colors hover:text-ember-400"
            >
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}

export function SiteFooter({ asOf }: { asOf?: string }) {
  return (
    <footer className="border-t border-white/5 py-10 text-sm text-mist-500">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-5 md:px-8">
        <p>
          Not investment advice. Model fair values are Monte Carlo NPVs under
          stated assumptions — not guarantees.
        </p>
        {asOf ? (
          <p className="font-mono text-xs">Market snapshot as of {asOf}</p>
        ) : null}
      </div>
    </footer>
  );
}
