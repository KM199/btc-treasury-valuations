# Overview

This project values **Bitcoin treasury preferred stock** — securities that pay high dividends, sit above common equity in the capital stack, and are economically tied to a company’s Bitcoin holdings.

## Two products in one repo

1. **SATA valuation pipeline** — Monte Carlo Bitcoin price paths → dividend sustainability → NPV fair value per share (`sata_valuation.py`).
2. **MSTR / STRC capital structure & hedge tooling** — live treasury scrape, senior claims, wipeout bands, options hedge notebooks.

A third surface is the **portfolio website** under `web/`: dark, generalist-friendly UI that shows market prices for MSTR, STRC, ASST, and SATA alongside model fair values.

## Plain-language thesis

Bitcoin treasury companies raise capital (equity, preferreds, converts) to buy Bitcoin. Preferred shares promise a dividend. Whether that dividend keeps getting paid depends on Bitcoin prices, cash reserves, and how much senior debt/preferred sits above you.

Our model asks: *Across thousands of plausible Bitcoin futures, how often do dividends get paid, and what is the present value of those cash flows?* That NPV is our **fair value**. Comparing it to the **market price** is the core story the site tells.

## Audience

Docs and the site aim at a smart generalist first. Formulas and parameter tables live in “Details” sections or in [`valuation.md`](valuation.md) / [`capital-structure.md`](capital-structure.md).

## Status map

| Piece | Status |
|-------|--------|
| SATA Monte Carlo | Production script |
| STRC Monte Carlo | Legacy notebook (`archive/` or `strc_valuation.ipynb`); being unified into a shared engine |
| HTML report | Legacy; website is the primary deliverable |
| Market snapshot JSON | Fed by `export_site_data.py` + scheduled CI |
