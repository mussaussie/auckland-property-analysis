# Auckland Property Analysis: Methodology Study Guide

Written 15 November 2026 so you can own every step of this project the way you owned the Adelaide one.
Read it top to bottom once, then use the exercises in section 9 to check your understanding against the code.

**Study order (about 2 hours):**
1. Sections 1–2: the big picture and the vocabulary (20 min)
2. Section 3: `download_data.py`, where each dataset comes from (20 min)
3. Section 4: `build_master.py`, how 38 columns are made (40 min, keep the script open beside it)
4. Section 5: `01_data_exploration.ipynb`, the flags and findings (30 min, run the notebook)
5. Sections 6–9: decisions, weak points, exercises

---

## 1. The big picture

```
 download_data.py          build_master.py                01_data_exploration.ipynb      (next) Files 2-4 → Streamlit
 ────────────────          ───────────────                ─────────────────────────      ────────────────────────────
 7 free sources   ──►  data/clean/master_dataset_     ──►  data/clean/master_flagged  ──►  analysis notebooks
 267 MB raw files       by_sa2.csv (633 rows x 38)          .csv (+ 5 flag columns)        then the dashboard
 in data/*/             data/clean/rent_timeseries_         visualizations/01_*.png
                        by_sa2.csv (73,523 rows)
```

### How this maps to your Adelaide project

| Adelaide | Auckland | Difference |
|---|---|---|
| `data_preparation_2019-2025.ipynb` (File 1) | `download_data.py` + `build_master.py` | Same job, but as scripts. Sources republish (MBIE every quarter), so the whole pipeline re-runs with two commands instead of re-running notebook cells by hand. |
| Outlier removal inside File 1 | `01_data_exploration.ipynb` (Auckland File 1) | Outliers are **flagged, not deleted**, so the dashboard can still show them, greyed out. |
| `historical_trend_analysis.ipynb` | Not possible for prices | Adelaide had 29 quarters of suburb sale prices. Auckland has only two capital valuations (2021, 2024). Rent has full history (1993–2026), so trends will be about rent. |
| `Price_prediction_model.ipynb` (Ridge) | Not planned | Two price points cannot train a time-based model. |
| `Rental_analysis.ipynb` | Planned File 2 | Auckland's rent data is stronger than Adelaide's: by SA2, quarterly, 30+ years. |
| `Deep_demo_analysis.ipynb` | Planned File 3 | Same census-driven idea. |
| `Investment_risk_analysis.ipynb` | Planned File 4 | Same idea, built only on analysis-ready SA2s. |

The format of each notebook copies Adelaide: a Purpose and Steps intro, `# STEP n` code cells, a saved CSV output, and a summary cell at the end.

---

## 2. Vocabulary you need

| Term | Meaning | Why it matters here |
|---|---|---|
| **SA2** (Statistical Area 2) | Stats NZ's neighbourhood unit, typically 2,000–4,000 residents. Auckland has 633 (2023 boundaries). | Our "suburb". Names are close to suburb names, but big suburbs are split (Ponsonby East / West). Adelaide used SAL suburbs; in NZ, SA2 is the unit every free source can be joined on. |
| **2018 vs 2023 SA2** | Stats NZ redrew some boundaries for the 2023 census. | MBIE rent still uses 2018 codes. Section 4.4 explains the fix. |
| **Meshblock** | The smallest Stats NZ area (a few dozen homes). | Police crime comes at meshblock level, which we sum up to SA2. |
| **Capital value (CV)** | Auckland Council's valuation of a property for rates: land + improvements. | Our stand-in for price, because sale prices by suburb are paid data (REINZ, QV, CoreLogic). CV is not a sale price. |
| **Land value (LV)** | The land part of the CV. | `land_share_of_cv_pct` shows how much of the value is land (high = older houses on big sections). |
| **Rating unit** | One row in the council rates database: a house, a flat, a shop, a factory, a car park. | There is **no property-type field**, so every median CV mixes homes and businesses. This is why File 1 needs flags. |
| **Bond** | Tenants lodge a bond with MBIE when a tenancy starts. MBIE publishes the median rent of new bonds. | Our rent figures are **new-tenancy rents across all dwelling types and bedroom counts**, not what sitting tenants pay. |
| **Active bonds** | Number of tenancies currently held. | Shows how big the rental market is in an SA2; a median from 30 bonds is weaker than one from 1,000. |
| **Gross yield** | Annual rent ÷ property value × 100. | Ours = median weekly rent × 52 ÷ median CV. "Gross" means before rates, insurance, maintenance and vacancy. |
| **Spatial join** | Matching a point (a house, a crime, a school) to the polygon (SA2) it sits inside. | How CVs, crime, schools and bus stops get an SA2, since none of those sources has one. Done with `geopandas.sjoin(..., predicate="within")`. |
| **Representative point** | A point guaranteed to be inside a polygon (a plain centroid can fall outside an odd-shaped area). | Used as each SA2's "centre" for the map and for the 2018→2023 rent link. |
| **Spearman correlation** | Correlation of the *ranks* instead of the raw values. | Our data is skewed (one $31m SA2), and Spearman isn't thrown off by extremes the way Pearson is. |

---

## 3. Stage 1: `download_data.py`, getting the raw data

Run with `python download_data.py`. Files that already exist are skipped, so it is safe to re-run. A clean run takes about 25 minutes.

| # | Function call | Source | How it is fetched | Output |
|---|---|---|---|---|
| 1 | `crime()` | NZ Police "Victimisations Time and Place" Tableau dashboard | No download button exists, so the script asks Tableau's CSV export for one month × one crime type at a time, filtered to the Auckland Region at meshblock level. | `crime/police_victimisations_auckland_meshblock.csv`: month, crime type, meshblock, lat/lon, count |
| 2 | `download(TENANCY …)` ×3 | MBIE tenancy bond data | Direct file download. File names contain the release month (`november-2026`), so **update them when MBIE republishes**. | `rental/` quarterly SA2 files 1993–2019 and 2020–2026, monthly by council |
| 3 | `download(gtfs…)` | Auckland Transport GTFS | Direct download | `amenities/at_gtfs.zip` (only `stops.txt` is used) |
| 4 | `ckan_url(...)` | Education Counts schools directory via data.govt.nz | Looks up the current file URL in the catalogue, then downloads it | `amenities/schools_directory.csv` (national) |
| 5 | `ckan_url("urban-development")` | HUD urban development data | Same as above | `property_prices/hud_ta_sales_rents.zip`: archived Urban Development `TA.csv`, Auckland-wide, used in File 5 Step 9 (`auckland_sales_quarterly.csv`) |
| 6 | `boundaries()` | Stats NZ ArcGIS services | Downloads national 2018 and 2023 SA2 polygons, keeps the 2023 SA2s whose inside point falls in the Auckland region | `boundaries/*.geojson` |
| 7 | `arcgis_table(census…)` ×4 | Stats NZ 2023 Census totals by topic | Pages through ArcGIS 2,000 rows at a time | `census/*_sa2.csv` plus a `_fields.csv` dictionary for each (column codes like `VAR_1_3` → meaning) |
| 8 | `arcgis_table(AKL …, centroid=True)` | Auckland Council rates valuation map service | Pages through 623,765 rating units and asks for each one's centre point | `property_prices/auckland_cv_2021_2024.csv` |

**Safety features worth knowing:**
- `get_json` retries up to 4 times, because these public services drop the odd request.
- Every download writes to a `.part` file and renames it only when complete, so a crash never leaves a half-file that a re-run would skip.
- `assert` lines stop the run if the result looks wrong (for example, fewer than 100,000 crimes, or not between 500 and 700 SA2s).

**Problems that were solved here (see SESSION_LOG.md for detail):** crime type names containing commas had to be escaped (`\,`) for Tableau; one census layer is published empty, so the unclipped twin (layer 3) is used.

---

## 4. Stage 2: `build_master.py`, building one row per SA2

Run with `python build_master.py` (about 1 minute). Keep the script open while reading this section; the headings follow its `# ---` comments.

### 4.1 Start from the boundaries
The 633 Auckland SA2 polygons are the **master list** (like "property suburbs as master list" in Adelaide). Every other source is joined onto them, so no SA2 is lost and none is invented. `lat`/`lon` = representative point.

### 4.2 Census (2023)
The script reads specific column codes from four census tables (the `CENSUS` dictionary at the top maps code → name).

| Column | Formula |
|---|---|
| `population_2023`, `median_age`, `households_2023`, `dwellings_2023`, `median_personal_income`, `median_household_income`, `census_median_rent_weekly` | Taken directly |
| `pct_overseas_born` | overseas-born ÷ people who stated a birthplace × 100 |
| `pct_european`, `pct_maori`, `pct_pacific`, `pct_asian` | ethnic group ÷ people who stated an ethnicity × 100. People can tick several groups, so these **add up to more than 100%**. |
| `pct_owner_occupied` | (owned + held in family trust) ÷ households that stated tenure × 100 |

**Cleaning rule:** negative numbers in Stats NZ files are suppression codes (counts too small to publish for privacy), not real values, so they become blank.

### 4.3 Capital values
1. Load all 623,765 rating units with their centre point.
2. Spatial join each point to its SA2.
3. Per SA2: count of units, **median** CV 2021, median CV 2024, median land value 2024.

| Column | Formula |
|---|---|
| `rating_units` | count of rating units in the SA2 |
| `median_cv_2021` | median of `CV` (valuation of 1 June 2021) |
| `median_cv_2024` | median of `LCV` (latest valuation, 1 May 2024) |
| `median_land_value_2024` | median of `LLV` |
| `cv_change_2021_2024_pct` | (median 2024 ÷ median 2021 − 1) × 100; median across analysis-ready SA2s −8.57%, against about −9% average residential movement in Auckland Council's 2024 revaluation release (cross-checked in the 17 Nov 2026 review) |
| `land_share_of_cv_pct` | median land value ÷ median CV × 100 (a ratio of medians, so it can reach exactly 100) |

**Why median, not mean:** one $50m office block would drag a mean up; the median is the middle property.

### 4.4 Rent (the trickiest join)
- MBIE publishes rent by **2018** SA2 code, but our master uses **2023** codes. Only 357 of 633 matched directly.
- Fix: for each 2023 SA2, find which 2018 SA2 its representative point falls inside, and use that 2018 area's rent.
- Consequence: when a 2018 SA2 was later split into several 2023 SA2s, all of them get the **same rent**. The 2018 code used is kept as `rent_source_sa2` in master and every rent export, and is the key for de-duplicating rent areas, sample counts and bond allocation. 142 SA2s share a source SA2 with another SA2 and are flagged later as `flag_borrowed_rent`.
- Only rows where `Dwelling Type = ALL` and `Number Of Beds = ALL` are kept, so rent is for all homes combined, not a 3-bedroom house.

| Column | Formula |
|---|---|
| `rent_timeseries_by_sa2.csv` | every quarter, every SA2: `rent_source_sa2`, median rent, active bonds, `lodged_bonds` (MBIE `Total Bonds`: new bonds lodged in the quarter) |
| `median_rent_weekly` | **average of the last 4 quarters'** medians (smooths quarter-to-quarter noise; only 580 SA2s have a figure in the single latest quarter) |
| `active_bonds` | active bonds in the latest quarter available |
| `rent_change_5y_pct` | (last-4-quarter average ÷ average of the quarters 5–6 years ago − 1) × 100 |
| `gross_yield_pct` | `median_rent_weekly` × 52 ÷ `median_cv_2024` × 100 |

### 4.5 Crime
- Uses the **latest 12 months** of the 4-year download.
- Each meshblock point is joined to its SA2, then counts are summed by crime type: `crime_assault`, `crime_burglary`, `crime_harm_or_endanger_persons`, `crime_robbery`, `crime_sexual_offences`, `crime_theft`, and `crime_total`.
- `crime_per_1000_residents` = crime_total ÷ population × 1,000, **left blank where population < 100** (a rate for 3 residents is meaningless).
- Known bias: crimes are counted where they happen, but divided by the people who **live** there. Malls and the CBD have many visitors and few residents, so their rate is inflated. Police also exclude crimes inside homes other than burglary.

### 4.6 Amenities
- `schools` = number of schools whose location falls in the SA2.
- `pt_stops` = number of bus/train/ferry stops, excluding "parent stations" (location_type 1), which would double count their platforms.

### 4.7 Checks before saving
The script asserts 633 unique rows, more than 500 SA2s with CV and more than 400 with rent, then saves to `data/clean/master_dataset_by_sa2.csv` and prints a summary.

---

## 5. Stage 3: `01_data_exploration.ipynb` (File 1)

This is where we first **looked** at the data. It is the step where you act as the analyst, so read the printed tables, not just the charts.

| Step | What it does | What it found |
|---|---|---|
| 1 Coverage | % of SA2s and % of residents with each measure | Rent covers 94.8% of SA2s but 99.1% of residents: the gaps are near-empty areas |
| 2 CV distribution | Histogram + top-12 table + `units_per_dwelling` | The top CVs mix Remuera/Herne Bay with Middlemore ($31m, hospital land) and industrial zones |
| 3 Flags | Builds 4 flags + `analysis_ready` | See table below |
| 4 CV maps | 2024 CV map and 2021→2024 change map | Median SA2 −8.6%; only 56 of 599 rose (rural fringe) |
| 5 Rent | Auckland trend line, distribution, cheapest and dearest | $255 → $662/wk (2000–2026), flat since 2024 |
| 6 Yield | Rent vs CV scatter with yield guide lines | Median 3.25%. Yields above 6% are all small CBD apartments |
| 7 Crime | Top 20 rates, before/after flags | Hotspots removed: median 28, max 271 per 1,000 (12 months) |
| 8 Correlation | Spearman matrix | CV moves with income (0.68), age (0.67), owner-occupation (0.56); yield ≈ inverse of CV (−0.93) |
| 9 Save | Writes `master_flagged.csv` and asserts it re-reads correctly | 633 rows, 43 columns |

### The flags (the most important decision in the project so far)

| Flag | Rule | Count | Reasoning |
|---|---|---|---|
| `units_per_dwelling` (helper) | rating_units ÷ dwellings_2023 | n/a | A housing area has about 1 rating unit per home (median 0.98). An industrial park has hundreds of units and almost no homes. |
| `flag_non_residential` | units_per_dwelling > 2, **or** fewer than 30 dwellings | 34 | 2 was chosen from the distribution: 90% of SA2s are under 1.23, and the jump starts around 1.7. The 30-dwelling rule catches Middlemore (3 dwellings, 5 units, so its ratio looked normal). |
| `flag_low_population` | fewer than 100 residents | 14 | Same cut-off already used for the crime rate. |
| `flag_borrowed_rent` | has a rent and shares its `rent_source_sa2` with another SA2 | 142 | Detects the 2018→2023 split explained in 4.4. **Label only**: the rent is real, just not unique. (Until 17 Nov 2026 the rule matched identical rent and bond values, which also caught Glenbrook and Grange by coincidence: 144.) |
| `flag_crime_hotspot` | crime_per_1000 > 300 | 27 | About 10× the median (29). Malls, town centres, CBD. **Label only**: CV and rent there are fine, but the crime rate isn't comparable. |
| `analysis_ready` | not non-residential **and** not low-population | 599 SA2s, 99.3% of residents | The set used for rankings, correlations and maps. |

**Key principle (different from Adelaide):** nothing is deleted. Flags travel with the data, so the dashboard can grey out or label areas and the user sees why.

---

## 6. One-off analysis: "5 best suburbs for a Muslim family, rent under $580"

**Superseded (17 Nov 2026 review).** The shortlist below filtered on *all-dwelling* rent. File 3 Step 8 now filters on the
requested dwelling type and bedrooms (`rent_by_type_sa2.csv`). For a 3-bed house under $580/wk: 567 SA2s pass the other
filters, 429 have a 3-bed house estimate, 4 are under budget on the published figures (Point England North and South at
$507, Tamaki West and East at $423: only 2 distinct MBIE rent areas), and **138 have no estimate**. Both rent areas fail the
stability check (Point England: $166, $650, $713, $500 on 6–9 new lodgements a quarter; Tāmaki: $180, $660, $640, $211 on
12–15), so **none is a confirmed match** until checked against the Tenancy Services six-month market rent tool or current
listings. None of the five names below meets $580 on 3-bed house rent:
four cost $628–698 and Aorere North has no estimate. The original method is kept for the record:
1. Religion is now in the master file (`pct_muslim`, added to `build_master.py` on 17 Nov). It comes from the census individuals table: 2023 *Religious affiliation (Islam)* ÷ *Total stated*. Auckland overall: **2.9%** (an earlier version of this guide said 0.85%, which was wrong). File 3 Step 8 reproduces this shortlist. The field codes were found by searching `census/census_2013_2018_2023_individuals_sa2_fields.csv` for "Islam".
2. Filter: `analysis_ready` and `median_rent_weekly < 580` → 56 SA2s.
3. Removed CBD apartment SA2s (student-heavy, unsuitable for families) and crime hotspots.
4. Ranked by Muslim share, then judged crime, schools and owner-occupation.
5. Result: Aorere North, Ōtāhuhu East, Kelston North, Ōtāhuhu South West, Ōtāhuhu South (runner-up: Te Atatū South-McLeod North).

**Correction:** the crime numbers quoted in that answer are per 1,000 residents over the **latest 12 months**, not 4 years as I first said.
**Limits:** rent is all dwelling types, so a 3-bedroom house will cost more (now confirmed, see above). Mosque distance was added on 18 Nov from a user-supplied list (`km_to_nearest_mosque`, File 3 Step 5).

---

## 7. Decision log

| Decision | Alternatives considered | Why this one |
|---|---|---|
| Rent + capital values instead of sale prices | REINZ / QV / CoreLogic (paid); HUD (city-level only) | Only free option with suburb-level detail |
| SA2 as the unit | Suburb names; meshblocks | Every source can be joined to SA2; meshblocks are too small for rent |
| Scripts for data prep, notebooks for analysis | All notebooks (Adelaide style) | Prep must re-run on every MBIE release; analysis needs explanation and charts |
| Median, not mean | Mean | Skewed values; one office block would distort a mean |
| Last 4 quarters for current rent | Latest quarter only | 20 more SA2s get a value, and the figure is less noisy |
| Flag outliers, don't delete | Delete (Adelaide approach) | Dashboard can still show them, and the reason is transparent |
| Spearman for correlations | Pearson | Robust to extreme values |
| Crime: latest 12 months | Full 4 years | Current picture; the 4-year file is kept for trend analysis later |

---

## 8. Weak points you should be ready to defend (or fix)

1. **CV is not price.** Valuations lag the market and the latest one is May 2024.
2. **CV medians still mix housing types** inside residential SA2s (an SA2 with many apartments shows a low median CV).
3. **The flag thresholds are judgement calls.** Change them in File 1 Step 3 and see what moves.
4. **Rent is all dwelling types combined.** MBIE does publish by bedroom count, and `build_master.py` filters to `ALL`. A per-bedroom version is a possible File 2 improvement.
5. **Shared rent** in 142 SA2s means neighbouring SA2s can't be compared on rent. Use `rent_source_sa2` to count distinct rent areas.
6. **The Auckland-wide rent line** in File 1 is a bond-weighted average of SA2 medians, not MBIE's official figure.
7. **Crime per resident** penalises busy areas; crime counts per km² or per visitor would be alternatives.
8. **Licence:** Auckland Council's CV service has no licence text; confirm reuse before publishing the dashboard.

---

## 9. Exercises to check your understanding

Do these in a scratch notebook (`import pandas as pd; m = pd.read_csv('data/clean/master_flagged.csv')`).

1. Find Remuera Waitaramoa. Recalculate its `gross_yield_pct` by hand from `median_rent_weekly` and `median_cv_2024`. (Answer: 1035.8 × 52 ÷ 3,275,000 × 100 ≈ 1.64%.)
2. List the 142 `flag_borrowed_rent` SA2s and group them by `rent_source_sa2`. Which 2018 areas were split the most?
3. In File 1 Step 3, change the non-residential threshold from 2 to 3. How many SA2s change, and which ones?
4. Why is Sylvia Park `analysis_ready = True` but `flag_crime_hotspot = True`? Explain in one sentence.
5. Open `data/census/census_2013_2018_2023_households_sa2_fields.csv` and find what `VAR_4_225` means. Check it matches `median_household_income`.
6. In `build_master.py`, find the line that sets `rent_change_5y_pct`. Which quarters count as "5 years ago"?
7. Explain to someone else why the yield for Symonds Street West (7.7%) does not mean it is a good investment.

If you can do all seven without help, you understand the pipeline as well as you understood Adelaide's.

---

## 10. Shared definitions and figures (after the 17 Nov 2026 review)

**Canonical version: `METRIC_RULES.md` (18 Nov 2026).** The dashboard and the AI agent cite that file; this section is the
background it was built from. If the two disagree, `METRIC_RULES.md` wins and this section should be corrected.

The dashboard and the AI agent should use these exact definitions and figures. Copies of the outputs before the review are in
`before_review_2026-11-17/`.

### Rent areas
- `rent_source_sa2`: the MBIE 2018 SA2 whose bond figures a 2023 SA2 uses. One source can feed several SA2s.
- Distinct rent areas: 527 in File 2; 507 with enough history in File 5. Count these, not SA2s, when saying how many
  independent rent observations a result rests on.

### File 2: area-level affordability
- 29.4% is the **median area ratio of annualised new-tenancy rent to all-household median income**. It mixes new-tenancy rent
  with the income of owners and renters, so it is **not rental stress**. Renter-specific income at SA2 is not in the data;
  rental stress stays an open item.
- `rent_by_type_sa2.csv`: one row per SA2 × dwelling type × bedrooms. Rent = mean of the last 4 quarterly medians;
  `quarters` = how many of the 4 had a published median; `rent_min_quarter` / `rent_max_quarter`; `lodged_bonds_4q` = **new**
  bonds lodged over the 4 quarters (the sample); `active_bonds` = all tenancies held in the latest quarter (**not** the sample).
- Sample checks: `flag_thin_sample` = fewer than 30 new lodgements over the 4 quarters (same minimum as File 6);
  `flag_unstable_rent` = highest quarterly median over 1.5× the lowest (99% of 3-bed house rent areas are under 1.41). Of 373
  3-bed house rent areas, 261 are thin (median 21 lodgements) and 3 unstable. `rent_metrics_by_sa2.csv` carries
  `lodged_3bed_house_4q` and `flag_verify_3bed_house` (either check); `bonds_3bed_house` there is active bonds.
- `data_note` on every 1-bed row: Tenancy Services warns that bonds recorded as one-bedroom have risen sharply and may not
  reflect the real bedroom count, so 1-bed counts and rents need caution. MBIE rounds counts to base 3 and suppresses
  figures for fewer than 5 bonds.

### File 3: family shortlist
- Budget filter uses the requested dwelling type and bedrooms. Show how many SA2s pass, how many lack an estimate, and how many
  distinct rent areas the qualifying SA2s use. Each row has `check`: `ok`, `verify` (fails a sample check) or `no estimate`.
  Only `ok` rows are budget matches; `verify` rows need a second source first. Result for 3-bed house, $580/wk: none `ok`
  (section 6); the cheapest `ok` 3-bed house estimates start at about $608 (Pukekohe).

### File 4: investment screen
- **Who is ranked: 481 of 530.** Complete cases only: the 34 missing an input are listed with `missing_inputs` (29 lack only
  rent volatility, 3 only 10-year rent growth, 1 both, 1 population change). **New developments** (`is_new_development`:
  population more than doubled 2018–23 **and** rent borrowed from a 2018 source SA2 shared with other SA2s) are also listed,
  not ranked: 15 complete ones; their 10-year growth and volatility describe the source area's older housing. Every unranked
  row has `not_ranked_reason`. An SA2 that doubled with its own rent series stays ranked with `flag_rapid_growth` (Long Bay).
- `lodged_3bed_house_4q` and `flag_verify_3bed_house` (File 2) are carried next to `rent_3bed_house`: 6 of the top 20 are
  marked verify (21–27 new lodgements a year).
- Capping population growth does not fix new developments: scores are percentile ranks, so a cap at 30% leaves the top 20
  unchanged. Ranking them would bring Pukekohe South West, Takanini South East and Takanini McLennan into the top 20.
- **Shared bonds** (`bonds_per_sa2`): a source SA2's active bonds split by each SA2's rented households, households × (1 −
  owner-occupied share), stored as `bond_share`. Against the previous even split: top 20 differs by 1 (Papakura Eastburn in,
  Wellsford out), Spearman 0.999. Rented households include social housing, which private bonds don't cover.
- Missing-data rule against the old skip-missing average, over the same 481: top 20 shares 18, Spearman **0.9998**, median
  shift 1 place, maximum 11.
- **Recent rent** (`rent_change_2y_pa`, File 5's annualised change over the last 2 years) is shown, not scored. Top 20:
  median −1.4% a year, 15 of 20 falling; other ranked SA2s −0.7%, 59% falling; 1 of the top 20 is among the 100 fastest-falling.
- Labels: **gross yield (2024 CV proxy)**: new-tenancy rent ÷ 2024 council capital value, which lags sale prices.
  **Recorded victimisations per 1,000 residents**: police-recorded, latest 12 months; it overstates risk in town centres and
  malls where few people live.
- The top 20 covers 16 distinct MBIE rent areas (11 of the 20 share rent with another SA2).

### File 5: rent trends
- $643 = the **average of the July, August and September 2026 monthly medians** ($640, $650, $640), not a quarterly median.
- **Turnover proxy** = bond closures ÷ active bonds. It is not a tenancy length; no average-tenancy-duration claim is made.
- Rent dipped briefly in 2020: $570 (Apr) → $550 (May), $560 (Jun) → $550 (Jul); back to $570 by Dec 2020 and $600 by
  Dec 2021. Do not say rent "never fell".
- The data does not say why rent cooled in 2025; no supply-versus-demand conclusion.

### File 6: new-tenancy rent gap (`rent_premium_pct`)
- An **observed gap** between two populations: new tenancies (bond medians) and all renting households (2023 Census). It is not
  what a tenanted property earns below market; no investor figure is drawn from it.
- Auckland: $603/wk (mean of six monthly bond medians, Oct 2022 – Mar 2023) against $540/wk (Stats NZ published 2023 Census
  median) = **+11.7% ($63/wk)**. Grouped-median interpolation ($545) is kept only as a check.
- **Sample rule:** 30+ new bonds lodged (MBIE `Total Bonds`, summed over Oct–Dec 2022 and Jan–Mar 2023, by source SA2:
  `lodged_census_time`). Shared-rent SA2s are excluded.

  | Minimum lodged | SA2s | Median gap | SA2s under 5% social | Their median gap |
  |---|---|---|---|---|
  | 20 | 366 | +12.1% | 158 | +8.1% |
  | **30 (used)** | **305** | **+11.2% ($64/wk)** | **129** | **+7.1% ($48/wk)** |
  | 50 | 166 | +9.5% | 67 | +5.9% |

- Every compared SA2 has a published median in both quarters (`rent_quarters_census_time` = 2).
- Quote the gap with its cut-off: it narrows as the minimum sample rises.

### File 7: communities
- Dissimilarity index: each community uses the same SA2s in all three census years (community × SA2 pairs missing a year are
  dropped). Against the earlier rule the largest change is 0.0015 (Buddhist 2023); Muslim 2013 is 0.394.
- Rent and other measures are **in the areas where members live**: the median across SA2s weighted by the group's head count
  (`area_weighted_*` columns). They are area figures, not what members pay or earn.
- Census shares show where people live, not where mosques, temples, halal shops or faith schools are. The facility measures
  are two straight-line distances from the SA2 centre (File 3): `km_to_al_madinah_coed` (Al-Madinah School, composite,
  co-educational) and `km_to_zayed_college_girls` (Zayed College for Girls, Years 7–15, girls only). Both schools are on
  Westney Road, Māngere, so the two distances differ by at most 0.3 km. `km_to_nearest_mosque` (with `nearest_mosque`) uses the
  same method on `mosques_verified.csv`: each of the user's 14 entries checked (18 Nov 2026) for a street address from the
  operator or a directory and an OpenStreetMap building at that address. 6 verified (4 with a corrected street, point or name),
  7 unverified, 1 duplicate (NZMA's "West Auckland Mosque" is its Rānui site); only verified entries are counted. **Schools by year level:** each MoE school type maps to the years it serves (Contributing 1–6, Full Primary 1–8, Intermediate
  7–8, Composite 1–15, Secondary 7–15 / 9–15 / 7–10 / 11–15, Restricted Composite 7–10); primary = any of Years 1–8, secondary =
  any of Years 9–13, Year 1 = starts at Year 1. Before 18 Nov composites counted as secondary only (Pinehurst, Albany South, was
  missed as a primary school). **In the area:** `*_in_area` counts facilities inside the SA2 polygon (spatial join, NZTM); every
  school and mosque point lands in exactly one SA2 (asserted). Zero is common, so each is paired with the nearest facility's
  name and straight-line distance from the SA2 centre (`nearest_*`, `km_to_nearest_*`). GP practices and halal food come from the Geofabrik NZ OpenStreetMap extract (`download_data.py` `osm_amenities()`, GDAL's OSM
  driver, points and building polygons, kept if inside an Auckland SA2). GP = amenity=doctors or healthcare=doctor, or a clinic
  named like a medical centre / A&M / urgent care; excluded if tagged with a non-general speciality or named like a specialist
  (keyword list). Halal = `diet:halal` yes/only, or "halal" in the name unless tagged no; `kind` butcher / shop / eatery.
  Both are incomplete (volunteer-mapped). Playgrounds and parks (session 11, `osm_parks()`): `leisure=playground` / `leisure=park`
  points and areas, each placed at one inside point; `access` private / no / customers dropped (220 features: school, childcare,
  fast-food playgrounds, private parks); unnamed playgrounds are labelled by the smallest mapped park containing them. One park
  point sits on a shared SA2 edge, so `count_in` keeps one SA2 per point. Mosque history 18 Nov: 11 points → 14 (user update) → 6 verified; median SA2 distance 3.9 → 3.5 → 6.0 km.
- The archived Urban Development `TA.csv` used here (`hud_ta_sales_rents.zip`) is by territorial authority, so it gives
  Auckland-wide sale prices. The ministry's separate Property and Sales Statistics dashboard and HPI do cover Auckland local
  boards; not used here. File 5 Step 9 uses the Auckland rows: median sale price (nominal and real, real in the latest quarter's
  dollars), HUD's Fisher price index and sales count, saved as `auckland_sales_quarterly.csv`. The newest quarter is
  `provisional` under the project's low-volume rule: sales under 75% of the previous 4 quarters' average (2026 Q1 had
  2,754), which suggests it is incomplete. Rent is compared on a common index (2021 Q4 price peak = 100), never on a second axis.

### File 8: rent forecast
- Target: mean new-tenancy rent over the next 4 quarters (year 1) and the 4 after (year 2), per MBIE rent area; the starting level
  is `median_rent_weekly`'s definition (asserted equal).
- Models: naive (flat), area 10-year trend, Auckland damped trend (Holt, damped, on log quarterly mean of the official monthly
  median, statsmodels), and their trend blend (added after the first run). Error = forecast ÷ actual − 1.
- Tests: trained to Sep 2024 and scored on Oct 2024 – Sep 2026 (the user's backtest), plus 13 September origins 2012–2024.
  Results: 2024 test naive 4.7 / 5.5%, Auckland 5.0 / 6.2%, blend 6.0 / 8.5%, area trend 7.3 / 11.4% (year 1 / 2);
  13 origins blend 5.0 / 6.3%, Auckland 5.1 / 6.9%, area trend 5.2 / 6.6%, naive 5.8 / 8.5%.
- **Decision to review:** Auckland trend used (near-best over 13 origins, clearly better than the trend models in 2024–26, reacts
  to the turn). Consequence: every area gets the same % change; areas differ only by level and band.
- Bands: 10th–90th percentile of the chosen model's errors over the 13 origins, split by thin sample (< 30 new bonds in 4
  quarters). Built from 2012–2023 origins only, they covered 79% of 2024–26 outcomes.

### Not done (and why)
- **Renter-only affordability.** The census pull has no household income by tenure, so no renter rent-to-income ratio. A
  modelled column (all-household income × 0.75) was rejected: the factor has no source.
- **Two-year rent change in the score.** Shown beside the score instead; a 0.5/0.3/0.2 growth blend would keep 16 of the top 20.
