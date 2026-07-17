# HEDGD (web)

Next.js front-end for Bitcoin treasury preferred valuations.

## Local

```bash
# from repo root — refresh JSON
python export_site_data.py

cd web
npm install
npm run dev
```

Open http://localhost:3000 (or the port Next prints).

## Deploy

Point Vercel at the `web/` directory (Root Directory = `web`). Site data lives in `public/data/` and is refreshed by GitHub Actions at the repo root.

## Design notes

Dark theme, Fraunces + DM Sans. Charts (Recharts) tell market-vs-fair and BTC-start elasticity stories. Screenshot QA is part of Definition of Done for UI changes.
