# S15 — Egg purchasing power, 1950–2025 (spreadsheet + charts) · **DONE**

Report: [r09](../reports/r09-egg-purchasing-power.md)

**Ask.** A dataset whose output is a spreadsheet and charts. The x axis is time
(1950–2025). The y axis is how many chicken eggs a person can buy with an average
income. It covers 13 countries: USA, UK, France, Germany, USSR (Russia), China,
Japan, Egypt, India, Italy, Argentina, Mexico and Thailand.

Engineering requirements: [`_engineering_requirements.md`](../sprints/_engineering_requirements.md)
(TDD-first, SOLID/DI, DRY, no overengineering).

## The data problem, stated honestly

No open dataset has egg prices for 13 countries back to 1950. The best open,
keyless and *consistent* combination is:

| Quantity | Source | Coverage |
|---|---|---|
| Egg price, LCU and SLC per tonne, plus the price index | FAOSTAT **Producer Prices** (`Prices_E_All_Data_(Normalized).zip`), item *Hen eggs in shell, fresh* | 1991–2024; the index runs to 2025 |
| Egg price, LCU per tonne (old currency units) | FAOSTAT **Producer Prices (old series)** (`PricesArchive_E_All_Data_(Normalized).zip`) | 1966–1990 |
| Average income: GNI per capita, current LCU | World Bank `NY.GNP.PCAP.CN` | 1960–2025; Russia from 1988 |

The axis spans 1950–2025, but **data begins in 1966**, where FAO prices begin.
Years before 1966 show as an honest gap, not as invented numbers. The price is
the farm-gate (producer) price, not retail, so it measures purchasing power
against what eggs cost to produce. A retail egg typically costs 1.5–3× as much.
That bias is the same for every country and every year, so the trends still
compare.

Both inputs are nominal and in the same currency in the same year, so

    eggs per year = GNI per capita [LCU] ÷ (price per tonne [LCU] × egg weight / 10⁶ g)

needs no deflator and no exchange rate.

### Harmonisation, done in the source (pure, unit-tested functions)

1. **Currency rebase.** Archive prices are in pre-reform currency: francs,
   Deutschmarks, lira, australes and Soviet rubles. Each country's
   SLC÷LCU ratio from the first year of the current series converts the archive
   into today's currency. That gives francs ÷ 6.55957, DM ÷ 1.95583,
   lira ÷ 1936.27, australes ÷ 10⁴ and old rubles ÷ 10³. Everything is derived
   from FAO's own numbers; nothing is hard-coded.
2. **Index extension.** The current series has holes: UK after 2006, India after
   1997, Thailand after 2020, Russia after 2022, and every country in 2025. FAO
   publishes a producer price **index** for the same item through 2025. A missing
   year is set to the nearest observed price × index(year) ÷ index(anchor year),
   and the row is tagged `price_basis: index-extended`.
3. **Explicit exclusions.** The archive "China" series is about 10× the current
   "China, mainland" series at the 1990/1991 seam, which is inconsistent with
   any plausible 1990 price. It is excluded in YAML, with a reason, rather than
   silently.

The USSR is spliced with Russia: FAO "USSR" prices up to 1990 and
"Russian Federation" from 1992. The World Bank has no USSR income, so
1966–1987 has prices but no income, and those years are excluded with a reason.

## Deliverables

- `faostat-prices` source (built-in): bulk download of both zips, filtered to one
  item and a declared set of areas → `{iso3, country, year, price_slc_per_tonne,
  price_basis}`.
- `scale(series, factor, divisor)` derive helper.
- `xlsx` writer (optional `openpyxl`, `pip install 'datavibes[xlsx]'`). It writes
  a long-form data sheet, a year × country pivot sheet with a native Excel line
  chart, and an *About* sheet with sources and method.
- `svg-small-multiples` writer: one panel per country on a shared log y axis
  and a fixed x range of 1950–2025. The other countries are drawn as grey context.
  The focus series is one hue, with a dashed segment where the price is
  index-extended, the latest value is labelled directly, and native `<title>`
  tooltips are included. Thirteen series exceed the eight-hue categorical
  ceiling, so the chart uses facets instead of a rainbow.
- Dataset `egg-purchasing-power` with parameters `EGG_WEIGHT_GRAMS` (60) and
  `EGG_FIRST_YEAR` (1950). Outputs: CSV, XLSX and SVG. Columns:
  `eggs_per_year`, `eggs_per_month`, `eggs_per_day` and `price_per_egg_lcu`.
- Tests: harmonisation functions, source parsing against a tiny zip fixture,
  `scale`, the xlsx writer (skipped without openpyxl), an SVG golden test, and
  an end-to-end dataset run on fixtures.

## Out of scope / backlog

- Pre-1966 prices: USDA NASS (US, needs a key) and national statistical yearbooks.
- Retail prices (ILO October Inquiry, BLS `APU0000708111`), as an alternative basis.
- USSR income 1966–1987 (Narodnoe khozyaistvo SSSR average wages).
