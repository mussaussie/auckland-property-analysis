# Auckland Property Analysis

Suburb-by-suburb analysis of the Auckland rental and property market, built on free public data and delivered as a
Streamlit dashboard. Every figure is keyed to a Stats NZ **SA2** area (633 in Auckland; 599 analysis-ready, covering
99.3% of residents).

## What's inside

| Part | What it does |
|---|---|
| `01`–`08` notebooks | The analysis. Each one writes a documented CSV to `data/clean/` and states its findings and caveats in a summary cell. |
| `app.py` | Streamlit dashboard: Overview, Rent in Auckland, Explore suburb, Compare suburbs, Opportunity finder, Map lab, Suburb in plain English, Find a rental under my budget, Family screen, Data & Methods, Glossary. |
| `search.py` | Shared data loading and rental search, used by the dashboard's filters and the planned AI chat (`python search.py` self-checks). |
| `release_checks.py` | Checks the figures and decisions the dashboard presents (`python release_checks.py`); run before every release. |
| `download_data.py` | Fetches every raw source into `data/`. |
| `build_master.py` | Joins the raw sources into one row per SA2 (`data/clean/master_dataset_by_sa2.csv`). |
| `METRIC_RULES.md` | Canonical definition, source, period and caveat for every metric, plus a "Never say" list. |
| `METHODOLOGY.md` | Every formula and decision. |

### The notebooks

| File | Topic | Output in `data/clean/` |
|---|---|---|
| 01 | Data exploration and quality flags | `master_flagged.csv` |
| 02 | Rent growth, dwelling type and bedrooms, affordability | `rent_metrics_by_sa2.csv`, `rent_by_type_sa2.csv` |
| 03 | Area profiles: population, communities, schools, transport, GPs, halal food, playgrounds, parks | `area_profiles_by_sa2.csv` |
| 04 | Risk / value screen (481 ranked house-dominated areas) | `risk_value_screen.csv` |
| 05 | Auckland rent trends 1993–2026 and cooling by area type | `auckland_rent_monthly.csv`, `rent_market_by_sa2.csv` |
| 06 | Census rent paid vs new-tenancy bond rent | `rent_premium_by_sa2.csv` |
| 07 | Communities 2013–2023: growth, hubs, segregation | `community_by_sa2.csv`, `community_summary.csv` |
| 08 | Experimental rent scenario with backtest against unchanged rent, and past-error ranges | `rent_forecast_by_sa2.csv`, `rent_forecast_backtest.csv` |

## Run the dashboard

The clean data is in the repo, so the dashboard runs straight after cloning:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Rebuild from raw data

Raw downloads (about 640 MB) are not in git. To re-create them and re-run the analysis:

```bash
pip install -r requirements-analysis.txt
python download_data.py
python build_master.py
```

Then run the notebooks in order, 01 to 08. Some source links carry a date in the file name and may need updating.

## Data sources

| Source | Used for |
|---|---|
| Stats NZ 2023 Census (also 2013, 2018) and SA2 boundaries | Population, households, income, tenure, religion, ethnicity |
| MBIE / Tenancy Services bond data | New-tenancy rent, quarterly by SA2 and monthly for Auckland |
| Auckland Council rating valuations (2021, 2024) | Capital value |
| NZ Police victimisation data | Recorded crime by area |
| Ministry of Education schools directory | Schools |
| Auckland Transport GTFS | Public transport stops |
| HUD Urban Development dataset | Auckland-wide sale prices |
| OpenStreetMap (© OpenStreetMap contributors, ODbL) | GPs, halal food, playgrounds, parks, map tiles |

## Read the numbers with their caveats

- **Rent** is new-tenancy bond rent, not what all renters pay; 142 areas share a rent series with a neighbour.
- **Gross yield** is a 2024 council-valuation proxy, not a sale-price yield, and is inflated in apartment areas.
- **Sale prices** are Auckland-wide only; there are no suburb sale prices in this project.
- **Rent forecasts** apply Auckland's damped trend to each area's current rent (about 5% typical error in a one-year backtest). Don't rank areas by them.
- **Crime** is recorded victimisations per resident, so busy centres look worse.
- **Census shares** show where people live, not where mosques, halal shops or faith schools are. Amenities from OpenStreetMap may be incomplete.

Full rules: [`METRIC_RULES.md`](METRIC_RULES.md). This is a research project, not financial or investment advice.
