# r09 — Egg purchasing power, 1950–2025 (S15)

Sprint: [s15](../done/s15-egg-purchasing-power.md)

## What shipped

| Piece | Where |
|---|---|
| `faostat-prices` source: FAOSTAT current and old-series bulk zips → one series per country in today's currency, each row tagged `observed` · `archive-rebased` · `index-extended` | `datavibes/sources/faostat.py` |
| `scale(x, factor, divisor)` derive helper | `datavibes/processing/functions.py` |
| `xlsx` writer: data sheet, pivots (`order`, `index_range`), native Excel chart, *About* sheet. Optional `openpyxl` (`datavibes[xlsx]`) | `datavibes/export/xlsx_writer.py` |
| `svg-small-multiples` writer: one panel per entity, shared log axis, pinned x range, grey context, dashed estimates, tooltips, light/dark | `datavibes/export/svg_small_multiples.py` |
| Dataset `egg-purchasing-power` (CSV + XLSX + SVG), parameter `EGG_WEIGHT_GRAMS` | `datasets/egg-purchasing-power/` |
| 18 tests (pure harmonisation, source on in-memory zips, writers, an SVG golden, end-to-end CSV golden, the parameter) | `tests/test_egg_purchasing_power.py` |

## Live run (2026-11-08)

719 country-years. Price basis: 376 observed, 265 archive-rebased, 78 index-extended.

Eggs one **month** of average income (GNI per capita) buys, at farm-gate prices:

| Country | Years | First year | 1990 | 2000 | 2025 |
|---|---|---|---|---|---|
| United States | 1966–2025 | 10,416 | 37,151 | 81,154 | 27,860 |
| United Kingdom | 1966–2025 | 5,534 | 25,535 | 40,367 | 85,102 |
| France | 1966–2025 | 4,839 | 30,347 | 38,539 | 34,761 |
| Germany | 1967–2025 | 3,852 | 19,543 | 31,901 | 33,457 |
| USSR / Russia | 1988–2025 | 2,616 | 3,179 | 3,861 | 18,978 |
| China | 1991–2025 | 643 | — | 2,890 | 12,264 |
| Japan | 1966–2025 | 3,055 | 23,924 | 34,328 | 23,414 |
| Egypt | 1967–2025 | 435 | 555 | 1,446 | 5,044 |
| India | 1967–2025 | 186 | 892 | 1,185 | 3,080 |
| Italy | 1966–2025 | 2,969 | 15,946 | 20,430 | 32,928 |
| Argentina | 1976–2025 | 5,409 | 6,608 | 13,878 | 7,772 |
| Mexico | 1966–2025 | 1,325 | 4,565 | 13,278 | 11,422 |
| Thailand | 1966–2025 | 576 | 3,108 | 4,243 | 7,904 |

The US fall after 2022 is real: avian influenza pushed US farm egg prices to records.

## Data findings

- **1950–1965 has no source.** FAO prices begin in 1966; the axis keeps the
  gap visible (x range pinned in the SVG, empty rows in the XLSX pivots).
- **Mexico switches currency inside FAO's old series.** Values are in old pesos
  until 1981 and new pesos from 1982. This is corrected with
  `archive_rescale: {MEX: {before: 1982, factor: 0.001}}`. Without the
  correction, 1966 read as about 1 egg a month.
- **FAO's old "China" series** is about 10× "China, mainland" at the 1990/91
  seam (39,555 vs 4,152 CNY/t), so it is excluded via `archive_exclude`.
- **India's price is flat at 10,230 INR/t for 1975–1997**: FAO estimates
  carried forward. Treat India's 1975–1997 trend as income-driven only.
- **Egypt's 1967–1975 and 1982–1990 prices are FAO estimates** (flag `E`).
  Its 1991–1993 values are index-extended backwards from 1994.
- **No USSR income** in the World Bank: USSR/Russia starts in 1988 with
  Russia's back-cast GNI. 1991 is a one-year gap: the USSR series ends in 1990
  and Russia's begins in 1992.
- The UK (after 2006), India (after 1997), Thailand (after 2020), Russia (after
  2022) and every country in 2025 rely on FAO's price index (`index-extended`,
  dashed in the chart).

## Tests

Full suite: everything green except `test_report.py::test_reporter_uses_packaged_template_by_default`,
which also fails without these changes. It needs the optional `weasyprint`
(`datavibes[report-html]`), which this venv lacks. `test_export.py`'s
"unknown writer" example moved from `xlsx` (now a real writer) to `ods`.

## Follow-up: second chart, graduates' pay

Ask: count only the average income of the highly educated population in cities.

**Source.** ILOSTAT `EAR_EMTA_SEX_EDU_NB_A`: average monthly earnings of
employees with *advanced* (tertiary) education, both sexes, current LCU.
**No source crosses education with urban/rural residence.** ILOSTAT has
earnings by education and earnings by area, but never both together, so the
chart shows graduates nationwide. Most tertiary-educated employees work in
cities anyway. There is no ILOSTAT education breakdown for Russia, China or
Japan; their panels are empty, with a note saying so.

**New building blocks.**
- An `ilostat` source. It keeps each country on its longest-running survey, so
  survey switches don't create jumps: Italy's establishment survey reads about
  2× its labour force survey. It also has `exclude_before`.
- An output `suffix`, so one writer can appear twice (`<ts>.graduates.svg`).
- `svg-small-multiples` options `reference_y`, `show_empty` and `empty_note`.

| Country | Years | First | Last | Everyone, last year |
|---|---|---|---|---|
| United States | 1994–2025 | 56,002 | 30,792 | 27,860 |
| United Kingdom | 1999–2025 | 54,442 | 86,637 | 85,102 |
| France | 2005–2025 | 53,734 | 26,227 | 34,761 |
| Germany | 2005–2022 | 53,018 | 58,123 | 38,683 |
| Italy | 2008–2020 | 24,954 | 20,297 | 29,007 |
| Egypt | 2010–2024 | 1,168 | 1,711 | 3,069 |
| India | 2018–2025 | 6,062 | 5,754 | 3,080 |
| Argentina | 2004–2025 | 10,352 | 7,479 | 7,772 |
| Mexico | 2002–2025 | 17,775 | 8,938 | 11,422 |
| Thailand | 2014–2025 | 8,863 | 9,898 | 7,904 |

**Caveat on the reference line.** "Everyone" is GNI per capita, which is gross
national income (capital income included) per head. Graduate figures are
employees' earnings as each household survey reports them, which is often
*net* pay (not yet verified per survey). Where the graduate line sits below
"everyone" (France, Italy, Mexico), the likely cause is that definitional
gap, not graduates earning less.

**Excluded.** Egypt 2008–2009 (55 and 91 EGP/month against 855 in 2010) are
dropped via `exclude_before` with that reason.

## Follow-up: third chart, city workers' pay

Ask: count only the city population.

**Source.** ILOSTAT `EAR_EMTA_SEX_GEO_NB_A` with `classif1: GEO_COV_URB`: the
average monthly earnings of employees in urban areas, all education levels and
both sexes. It is the same `ilostat` source with a different slice; no new
code. Russia, China and Japan have no urban breakdown, Argentina has a single
year (2005) and the UK stops in 2018. Egypt 2008–2009 shows the same ~10×
glitch as the education series, so it is excluded the same way (a shared YAML
anchor). Mexico has no 2020 survey, which leaves a one-year gap.

| Country | Years | First | Last | Everyone, last year |
|---|---|---|---|---|
| Argentina | 2005–2005 | 6,244 | 6,244 | 9,126 |
| Germany | 2005–2022 | 41,585 | 42,601 | 38,683 |
| Egypt | 2010–2024 | 1,128 | 1,592 | 3,069 |
| France | 2005–2025 | 37,706 | 21,755 | 34,761 |
| United Kingdom | 2005–2018 | 103,577 | 85,067 | 66,906 |
| India | 2018–2025 | 4,215 | 4,142 | 3,080 |
| Italy | 2007–2025 | 45,769 | 37,147 | 32,928 |
| Mexico | 2002–2025 | 8,676 | 5,969 | 11,422 |
| Thailand | 2014–2025 | 5,601 | 6,775 | 7,904 |
| United States | 2005–2025 | 107,032 | 24,236 | 27,860 |

The same caveat applies to the reference line: GNI per capita is not take-home pay.

## Follow-up: seven more countries

Added: Poland, Greece, Israel, Iran, Brazil, Chile and Norway (20 countries in all).

**FAO price corrections, all declared in `dataset.yaml` with reasons:**
- **Poland:** FAO's old series is already in new złoty in 1989–1990 (1 : 10,000),
  while 1966–1988 and the 1991 current series are in old złoty. Handled with
  `archive_rescale: {POL: {from: 1989, factor: 10000}}`; the rescale option
  now takes `from` as well as `before`. The World Bank has no Polish income
  before 1990, so the series starts in 1990.
- **Brazil:** archive prices for 1973–1982 are rounded to 0.01–0.17
  cruzeiros/tonne, too few digits to use. They are dropped with
  `archive_exclude: {BRA: {before: 1983}}`, which can now drop just the early years.
- **Iran:** FAO has one observed price after 1990 (2002). Chaining FAO's price
  index 22 years from that one anchor gave about 4× too many eggs by 2024, so
  the new `index_exclude: {IRN: …}` switches the extension off. Iran shows
  1967–1990 plus 2002 only.
- **Israel:** FAO's observed price drops 38% in 2000 (4,464 → 2,751 NIS/t). It
  is kept, since it is FAO's own figure, but it explains the jump.
- **Chile:** current FAO prices stop in 2012; 2013–2025 is index-extended.

**ILOSTAT currency bug found and fixed.** ILOSTAT's "local currency" earnings
from EU Structure-of-Earnings surveys are actually **euros** for non-euro
countries. The UK `BB:3056`, Norway `BB:3054` and Poland `BB:13355` are all
affected: the ratio of the USD figure to the "LCU" figure equals the
EUR/USD rate (1.326 in 2010). Both ILOSTAT sources now read the `_CUR_`
indicators in **USD** and convert them with the World Bank's official annual
rate (`PA.NUS.FCRF`, new helper `product`). This corrected:
- the UK urban series (85k → 75k eggs in 2018);
- Norway's graduates (6k → 50k);
- Poland's graduates;
- Brazil's pre-1994 graduate pay, which had come through in cruzeiros.

**Coverage of the new countries in the second and third charts:**
- **Israel and Iran:** no ILOSTAT breakdown.
- **Brazil:** graduates 1995–2011 (the longest survey; a newer 2012+
  survey is not mixed in), urban 2012–2025.
- **Chile:** scattered survey years. A small change to the chart writer now
  draws isolated years as dots, since a single year has no line segment.

**Writer fixes found along the way:**
- Long footer lines now wrap.
- A log axis where every value is equal no longer divides by zero.

Tests: 29 in `tests/test_egg_purchasing_power.py`, all green.

## Follow-up: fourth chart, a new 100 m² home priced in eggs

Ask: the cost of buying a new 100 m² house, in eggs, per country. Decision
(asked): researched anchors chained with indices, using new dwellings
nationally where possible.

**The data reality.** No open dataset has housing price *levels* per m² across
these countries over time.
- The **BIS** publishes long nominal price **indices** (`WS_SPP`) for 17 of
  the 20 countries; Egypt, Iran and Argentina have none.
- BIS **levels** per m² (`WS_DPP`) exist only for France (new flats,
  national, 1995+), Russia (new dwellings, urban, 2001+), Poland (flats,
  national, 2003–2024) and Norway (all dwellings, national, back to 1819, in
  thousand NOK).

So each country is one of:
- **observed BIS levels** (solid line), index-extended at the ends;
- **one researched anchor** price per m², chained through its BIS index (dashed);
- **empty**: Israel has an index but no per-m² level anywhere; Egypt, Iran and
  Argentina have no national series.

| Anchor | Year | LCU/m² | Confidence | Source / definition |
|---|---|---|---|---|
| USA | 2025 | 2,048 | medium | Census SOC: median new single-family price $417,400 ÷ median 2,194 sq ft (incl. land) |
| GBR | 2021 | 2,971 | medium | ONS regional price levels per m², unweighted mean of 9 English regions + Wales (all dwellings) |
| DEU | 2025 | 5,478 | low | Global Property Guide H1 2025, primary (new) properties nationwide |
| CHN | 2024 | 10,419 | high | NBS: residential sales CNY 8,486.4 bn ÷ 814.50 mn m² |
| JPN | 2024 | 943,000 | high | Real Estate Economic Institute: nationwide new condominiums |
| IND | 2024 | 92,463 | low | ANAROCK: top-7-city average INR 8,590/sq ft |
| ITA | 2024 | 1,500 | medium | OMI/ABI: ~EUR 114 bn ÷ ~76 mn m² of dwellings sold (all dwellings) |
| MEX | 2025 | 31,397 | low | Banorte INBAPREVI Nov 2025, national, all housing |
| THA | 2024 | 106,094 | low | REIC: condos transferred to foreigners, THB 4.7 m ÷ 44.1 m² |
| GRC | 2024 | 3,000 | low | RE/MAX Hellas: new properties nationwide (listing prices) |
| BRA | 2024 | 9,366 | medium | FipeZap Dec 2024: apartments for sale, 56 cities (listing prices) |
| CHL | 2024 | 2,957,000 | low | CChC Q4 2024: new apartments 77.3 UF/m² (Gran Santiago) × UF ≈ CLP 38,250 |

The anchor definitions differ: new vs all dwellings, national vs big cities,
listing vs transaction prices. **Trends within a country are more reliable than
levels between countries.** The chain uses the BIS index for *all* dwellings,
even where the anchor is for new ones.

| Country | Years | First | Last | Observed / anchor years |
|---|---|---|---|---|
| Brazil | 2001–2025 | 1.15 M | 2.79 M | 1 of 25 |
| Chile | 2002–2025 | 1.35 M | 4.22 M | 1 of 24 |
| China | 2005–2025 | 1.90 M | 1.45 M | 1 of 21 |
| Germany | 1970–2025 | 1.58 M | 3.96 M | 1 of 56 |
| France | 1970–2025 | 1.13 M | 4.58 M | 31 of 56 |
| United Kingdom | 1968–2025 | 0.35 M | 7.89 M | 1 of 58 |
| Greece | 1997–2025 | 1.39 M | 1.33 M | 1 of 29 |
| India | 2009–2025 | 0.88 M | 1.52 M | 1 of 17 |
| Italy | 1966–2025 | 0.23 M | 1.61 M | 1 of 60 |
| Japan | 1966–2025 | 1.03 M | 4.84 M | 1 of 60 |
| Mexico | 2005–2025 | 1.62 M | 1.66 M | 1 of 21 |
| Norway | 1966–2025 | 0.26 M | 3.43 M | 53 of 60 |
| Poland | 2003–2025 | 0.59 M | 1.94 M | 22 of 23 |
| USSR / Russia | 2001–2025 | 0.74 M | 3.24 M | 25 of 25 |
| Thailand | 1991–2025 | 3.37 M | 3.97 M | 1 of 35 |
| United States | 1970–2025 | 0.28 M | 0.77 M | 1 of 56 |

**New building blocks.**
- `bis-series`: a source for BIS bulk files that matches on codes,
  averages per year and supports a per-series multiplier.
- `chain_index`: a generic processing step (level × index ÷ index at the
  nearest anchor). The pure `extend_with_index` moved from the FAO source to
  `processing/functions.py`, so both share it.

**Gotcha:** YAML reads a bare `NO` (Norway's BIS code) as the boolean
false, so it must be quoted. Documented in `reference.md`.

Tests: 33 in `tests/test_egg_purchasing_power.py`, all green.

## Follow-up: fifth chart, sterling silver per month of average income

**Method.**

    grams of sterling silver per month = (GNI per capita, Atlas method, current USD) ÷ 12
                                         ÷ (silver USD/troy oz × 0.925 ÷ 31.1034768 g/oz)

Sterling silver is 92.5 % silver. This is metal value only; finished sterling
goods carry a making charge on top.

**Sources.**
- **Silver price:** World Bank Commodity Price Data ("Pink Sheet"), annual
  nominal, 1960–2025. The source rounds it to 0.1 USD, which is up to ~10 %
  in the 1960s, when silver was about 1 USD/oz.
- **Income:** World Bank `NY.GNP.PCAP.CD` (Atlas), 1962→. USSR has none;
  Russia starts in 1991 and Poland in 1992.

**Why dollars, not local currency.** The World Bank's official exchange rate
(`PA.NUS.FCRF`) is quoted in pre-euro currencies before 1999 (4.2 DM per USD
in 1960) and in old rubles before 1998. Its local-currency GNI, however, is
back-converted to euros and new rubles, so mixing the two is off by 1.96×
(DM) up to 1000× (rubles). Staying in USD needs no exchange rate. The earlier
ILOSTAT USD → LCU conversion is unaffected: all its years fall after each
country's last redenomination.

**Pipeline changes.**
- `worldbank-pinksheet` source: reads the current file link from the
  commodity-markets page, because the file URL carries a monthly release hash.
- `lookup` now matches keys as text. Before `normalize`, the World Bank's
  years are strings and other sources' are integers.
- New `map` step: labels every row's `country` from its ISO3 code, so rows
  without an FAO price don't carry the World Bank's names ("Russian
  Federation") and split the panels.
- The two egg-only filters became one `any` filter: a country-year is kept if
  any chart can use it. Silver therefore covers 1962–2025 instead of starting
  at FAO's 1966. The egg charts are unchanged.

| Country | 1970 | 1980 (silver spike) | 2000 | 2025 |
|---|---|---|---|---|
| United States | 8,157 | 1,804 | 20,153 | 6,253 |
| Norway | 4,888 | 2,108 | 20,500 | 6,851 |
| Japan | 3,082 | 1,513 | 20,921 | 2,699 |
| China | 187 | 30 | 532 | 1,002 |
| India | 187 | 36 | 247 | 194 |

Tests: 37 in `tests/test_egg_purchasing_power.py`, all green.

## Follow-up: sixth chart, sterling silver in pounds per year

This is the same data as the grams chart, restated per year in avoirdupois
pounds:

    lb per year = grams per month × 12 ÷ 453.59237

The new column is `sterling_lbs_per_year`. The chart is `<ts>.silver-lbs.svg`,
and the xlsx tab is "sterling silver lbs per year". A troy pound (373.24 g)
would read 21.5 % higher. That is noted in the xlsx.

| Country | 1970 | 1980 | 2000 | 2025 |
|---|---|---|---|---|
| United States | 215.8 | 47.7 | 533.2 | 165.4 |
| Norway | 129.3 | 55.8 | 542.3 | 181.2 |
| Japan | 81.5 | 40.0 | 553.5 | 71.4 |
| Germany | 107.1 | 46.5 | 391.1 | 112.1 |
| China | 4.9 | 0.8 | 14.1 | 26.5 |
| India | 4.9 | 1.0 | 6.5 | 5.1 |

## Follow-up: seventh chart, a middle-class car priced in eggs

**The car.** A compact family sedan: the Toyota Corolla where it is the
mainstream choice, otherwise the local equivalent (Lada Vesta in Russia,
Maruti Dzire in India, Saipa Shahin in Iran). Each country has one researched
2025 list price; Norway's is from 2019, the newest list found. Every price is
recorded with its model, source and confidence in the xlsx *About* sheet and in
`car_anchor_note`.

**Back in time.** The new `chain_index` mode splices indices year by year,
using the best index first:
1. **New-car CPI:** US BLS `CUUR0000SETA01` (1953→, via the new
   `bls-series` source) and Eurostat HICP 07.1.1 (1996→) for Germany, Greece,
   France, Italy, Poland, Norway, and the UK up to 2019.
2. **General CPI:** World Bank `FP.CPI.TOTL` everywhere else and earlier.

The UK is why splicing was needed. Its car index stops before the 2025 anchor,
so with a single-index chain the general CPI took every year. Spliced, the
CPI bridges 2025→2019 and the car index carries 1996–2018. That moved the UK's
1970 figure from 126k to 215k eggs, because new-car prices rose much more
slowly than prices in general.

**Caveats.**
- The CPI understates how expensive cars were long ago: Japan's chain gives
  about ¥690k for 1966 against a real ¥432k Corolla.
- The car index is quality-adjusted. The line tracks "a new car", not one model.
- The World Bank has no Argentine CPI, so Argentina shows only 2025. Iran shows
  1967–2002, the years with an FAO egg price.

| Country | Years | 1970 | 2000 | Latest |
|---|---|---|---|---|
| Argentina | 2025–2025 | — | — | 169k |
| Brazil | 1983–2025 | — | 328k | 448k |
| Chile | 1970–2025 | 119k | 259k | 331k |
| China | 1991–2025 | — | 339k | 188k |
| Germany | 1967–2025 | 107k | 316k | 241k |
| Egypt | 1967–2025 | 193k | 306k | 537k |
| France | 1966–2025 | 199k | 478k | 327k |
| United Kingdom | 1966–2025 | 215k | 623k | 717k |
| Greece | 1967–2025 | 131k | 232k | 88k |
| India | 1967–2025 | 40k | 112k | 108k |
| Iran | 1967–2002 | 145k | — | 232k |
| Israel | 1966–2025 | 141k | 621k | 572k |
| Italy | 1966–2025 | 129k | 243k | 343k |
| Japan | 1966–2025 | 61k | 188k | 112k |
| Mexico | 1966–2025 | 90k | 318k | 223k |
| Norway | 1966–2025 | 134k | 397k | 237k |
| Poland | 1970–2025 | 246k | 550k | 222k |
| USSR / Russia | 1992–2025 | — | 133k | 200k |
| Thailand | 1966–2025 | 184k | 365k | 329k |
| United States | 1966–2025 | 201k | 472k | 83k |

Tests: 41 in `tests/test_egg_purchasing_power.py`, all green. They cover
the BLS windows and refusals, splicing, and an end-to-end car price chained
from the anchor.
