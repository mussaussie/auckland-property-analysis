# Metric Rules: Auckland Property Analysis

The single reference for every number the Streamlit dashboard shows and the AI agent quotes. Each metric has one canonical
column, source, geography, period, sample rule and caveat. `METHODOLOGY.md` explains how and why; this file says **what to
show and what to say**.

Last updated: 18 November 2026 (after the 17 Nov review rounds; HUD sale prices, mosque distance, playgrounds, parks and the File 8 rent forecast added). Pre-review outputs: `before_review_2026-11-17/`.

## Rules of use

1. **Read numbers from the clean CSVs in `data/clean/`, never from notebooks or memory.** Join on `sa2_code`.
2. **Quote a metric with its label and caveat from this file.** For example, "gross yield (2024 CV proxy)", never just "yield".
3. **Respect the flags.** Show flagged values with their badge; do not silently drop them or present them as clean.
4. **Count rent areas, not SA2s,** when saying how many independent rent observations a result rests on (`rent_source_sa2`).
5. **If a metric is not in this file, the data does not have it.** Say so rather than estimating (see "Not in the data").
6. Auckland-wide figures come from the "Auckland headline figures" table, not from averaging SA2 columns.

## Data vintages

| Source | What | Period used | Geography |
|---|---|---|---|
| Stats NZ 2023 Census | Population, households, income, tenure, religion, ethnicity, census rent paid | Census night, 7 March 2023 (also 2013, 2018) | SA2 2023 |
| MBIE / Tenancy Services bond data | New-tenancy rent, bonds lodged, active, closed | Quarterly to Jul–Sep 2026; monthly Auckland series Feb 1993 – Sep 2026 | 2018 SA2 (`rent_source_sa2`), Auckland |
| Auckland Council rating valuations | Capital value (CV), land value | 1 June 2021 and 1 May 2024 | Rating unit → SA2 |
| NZ Police victimisations | Recorded victimisations by type | Oct 2025 – Sep 2026 (latest 12 months) | Meshblock → SA2 |
| Ministry of Education schools directory | School locations, type, co-ed status | Downloaded Nov 2026 | Point |
| Auckland Transport GTFS | Public transport stop locations | Downloaded Nov 2026 | Point |
| HUD archived Urban Development dataset (`TA.csv`) | Median sale price, sales count, price index | Quarterly, 1993 Q1 – 2025 Q4 complete; 2026 Q1 provisional (project low-volume rule) | Auckland-wide (the ministry's separate local-board HPI is not used) |
| OpenStreetMap (Geofabrik NZ extract, ODbL) | GP practices (`gp_clinics_auckland.csv`, 328), halal food places (`halal_shops_auckland.csv`, 151, 17 butchers), public playgrounds (`playgrounds_auckland.csv`, 1,470) and parks (`parks_auckland.csv`, 3,320); main-chain supermarkets (`supermarkets_auckland.csv`, 124) and shopping centres (`shopping_centres_auckland.csv`, 33), extracted 24 Nov 2026 | Extract dated 17 Nov 2026 | Point |
| Mosque register (`mosques_verified.csv`, from the user's 14-entry `mosques_user_list.csv`) | 6 verified mosques (8 entries unverified or duplicate, not counted) | Checked 18 Nov 2026 | Point: OpenStreetMap building at the verified address |

MBIE counts are randomly rounded to base 3 and suppressed below 5 bonds. Census counts are randomly rounded to base 3.

## Geography and keys

| Item | Rule |
|---|---|
| `sa2_code` | Stats NZ SA2 2023. 633 in Auckland. The join key for every file. SA2s are not suburbs: names are close, boundaries differ. |
| `rent_source_sa2` | The MBIE 2018 SA2 whose bond figures an SA2 uses. 527 distinct rent areas in File 2. |
| `flag_borrowed_rent` | SA2 shares its `rent_source_sa2` with another SA2 (142 SA2s). Badge: "Shares rent figures with a neighbouring area". |
| `analysis_ready` | Not non-residential and 100+ residents: 599 SA2s, 99.3% of residents. Rankings, correlations and maps use these only. |
| `flag_crime_hotspot` | `crime_per_1000_residents` > 300 (27 SA2s: malls, town centres, CBD). Crime rate not comparable; left out of the investment screen. |

## Metrics

### Value and price

| Metric | Column (file) | Definition | Sample / threshold | Caveat to state |
|---|---|---|---|---|
| Capital value | `median_cv_2024` (`master_flagged`) | Median council CV of all rating units in the SA2, 1 May 2024 | All rating units | **Not a sale price.** A council valuation that lags the market; mixes all property types, including commercial. |
| CV change | `cv_change_2021_2024_pct` (`master_flagged`) | (median CV 2024 ÷ median CV 2021 − 1) × 100 | All rating units | Two valuation dates only, so no price trend in between. Median SA2 −8.57%, close to the Council's reported residential average of about −9%. |
| Gross yield | `gross_yield_pct` (`master_flagged`, `risk_value_screen`) | `median_rent_weekly` × 52 ÷ `median_cv_2024` × 100 | Rent and CV both present | **"Gross yield (2024 CV proxy)".** New-tenancy rent over council CV, not over a sale price; before costs. Inflated in apartment SA2s, where small units have low CVs. |
| Auckland sale price | `median_sale_price`, `median_sale_price_real` (`auckland_sales_quarterly`) | HUD median price of homes sold in the quarter; real = in Dec 2025 dollars | Skip rows with `provisional` = True | **"The archived Urban Development TA.csv used here is Auckland-wide."** (The ministry's Property and Sales Statistics dashboard and HPI cover local boards; not used.) Moves with the mix of homes sold. |
| Auckland price index | `hpi` (`auckland_sales_quarterly`) | HUD Fisher price index (1993 Q1 ≈ 1) | As above | The better measure of price **trend**; the median is the better "typical price". |
| Auckland sales volume | `sales_count` (`auckland_sales_quarterly`) | Sales recorded in the quarter | As above | `provisional` = the project's low-volume rule: the latest quarter's count is under 75% of the previous four quarters' average, which suggests it is incomplete. |

### Rent

| Metric | Column (file) | Definition | Sample / threshold | Caveat to state |
|---|---|---|---|---|
| Current rent, all dwellings | `median_rent_weekly` (`master_flagged`, `rent_metrics_by_sa2`) | Mean of the last 4 quarterly MBIE bond medians (all dwelling types and bedrooms) | Published medians only | **New-tenancy rent**, not what sitting tenants pay. Shared across SA2s with the same `rent_source_sa2`. |
| Rent by dwelling and bedrooms | `rent` (`rent_by_type_sa2`) | Mean of the last 4 quarterly medians for that dwelling type × bedrooms | `lodged_bonds_4q` = new bonds over 4 quarters (the sample); `quarters` with a median | Check `flag_thin_sample` and `flag_unstable_rent` before using as a price. 1-bed rows carry `data_note` (Tenancy Services warning that bedroom counts may be wrong). |
| 3-bed house rent | `rent_3bed_house` (`rent_metrics_by_sa2`, `risk_value_screen`) | As above for House × 3 bedrooms | `lodged_3bed_house_4q`; `flag_verify_3bed_house` = fewer than 30 new lodgements **or** highest quarterly median over 1.5× the lowest | Show a **"verify"** badge when flagged (293 SA2s). `bonds_3bed_house` is *active* bonds, not the sample. |
| Rent sample size | `lodged_bonds_4q`, `lodged_3bed_house_4q` | New bonds lodged (MBIE `Total Bonds`) | — | Use these, not active bonds, for "how many rents is this based on". |
| Rent growth, 10 years | `rent_cagr_10y_pct` (`rent_metrics_by_sa2`) | (current rent ÷ rent 10 years earlier)^(1/10) − 1, % a year | Needs both points | Past performance. For new developments it describes the older housing of the source area. |
| Rent change, 1 / 5 / 10 years | `rent_change_1y_pct`, `rent_change_5y_pct`, `rent_change_10y_pct` (`rent_metrics_by_sa2`) | Current rent against rent 1, 5 and 10 years earlier | — | Total change, not a yearly rate. |
| Recent rent change | `cooling_pa` (`rent_market_by_sa2`), `rent_change_2y_pa` (`risk_value_screen`) | 4-quarter mean now ÷ 4-quarter mean 2 years ago, annualised | — | Shown, **not scored**. Two-year changes are noisy. |
| Boom-period growth | `boom_pa` (`rent_market_by_sa2`) | 4-quarter mean mid-2024 ÷ mid-2020, annualised | — | — |
| Rent volatility | `rent_volatility` (`risk_value_screen`) | Standard deviation of year-on-year % change in quarterly median, last 10 years | 20+ year-on-year points | High values often mean a thin rental market, not just a risky one. |
| Turnover proxy | `turnover_pct` (`rent_market_by_sa2`) | Bonds closed over 4 quarters ÷ mean active bonds × 100 | — | **A proxy**, not a tenancy length. Never convert it to an average tenancy duration. |
| Rent spread | `rent_spread` (`rent_market_by_sa2`) | Upper-quartile ÷ lower-quartile bond rent | — | Mixes dwelling types. |

### Rent against census (File 6)

| Metric | Column (file) | Definition | Sample / threshold | Caveat to state |
|---|---|---|---|---|
| New-tenancy rent gap | `rent_premium_pct`, `rent_premium_dollars` (`rent_premium_by_sa2`) | Bond median (Oct 2022 – Mar 2023) ÷ census median rent paid (March 2023) − 1 | `in_premium_analysis`: 30+ new bonds lodged over the two quarters (`lodged_census_time`), not shared rent, both medians present: 305 SA2s | **"Observed gap"** between two populations: new tenancies and all renting households. It is not what a tenanted property earns below market. Quote it with its cut-off: 20 → +12.1%, 30 → +11.2%, 50 → +9.5%. The column name keeps "premium" for code; the label must say "gap". |
| Census rent paid | `census_median_rent_weekly` (`master_flagged`) | Stats NZ median weekly rent paid by all renting households | — | Includes social housing (income-related rent) and long-stay tenants. |

### Affordability

| Metric | Column (file) | Definition | Sample / threshold | Caveat to state |
|---|---|---|---|---|
| Area rent-to-income ratio | `rent_to_income_pct` (`rent_metrics_by_sa2`) | 2023 mean bond rent (`rent_2023_weekly`) × 52 ÷ census median household income (all households) × 100 | — | **"Area-level ratio of new-tenancy rent to all-household income"**: **not rental stress**. Income includes owners. Median across SA2s 29.4%. |

### Risk

| Metric | Column (file) | Definition | Sample / threshold | Caveat to state |
|---|---|---|---|---|
| Crime rate | `crime_per_1000_residents` (`master_flagged`) | Recorded victimisations, latest 12 months, ÷ residents × 1,000 | Blank where fewer than 100 residents | **"Recorded victimisations per 1,000 residents."** Counted where crime happens but divided by people who live there, so busy centres look worse. Police data leaves out crimes inside homes other than burglary. |
| Crime by type | `crime_assault`, `crime_burglary`, `crime_theft`, … (`master_flagged`) | Counts, latest 12 months | — | Counts, not rates. |
| Rental market depth | `bonds_per_sa2` (`risk_value_screen`) | Active bonds of the rent area × `bond_share` (the SA2's share of the area's rented households) | — | Rented households include social housing, which private bonds don't cover. |

### Investment screen (File 4, `risk_value_screen.csv`)

| Item | Rule | Caveat to state |
|---|---|---|
| Who is ranked | `ranked` = analysis-ready, not a crime hotspot, 50%+ separate houses, has rent and CV, **all seven inputs**, not a new development: **481 of 530** | Unranked rows give `not_ranked_reason`. Show them listed, not hidden. |
| New development | `is_new_development` = population more than doubled 2018–23 **and** `flag_borrowed_rent` (15 complete SA2s) | Badge: "New development zone – historical rent metrics reflect the 2018 parent area". |
| Rapid growth | `flag_rapid_growth` = population more than doubled **without** borrowed rent (Long Bay) | Ranked. Badge: "Rapid growth". |
| Scores | `s_*` = percentile rank within the 481 (100 = best for an investor); `value_score`, `growth_score`, `risk_score` = group means; `score_Balanced` / `score_Income-focused` / `score_Cautious` = weights (⅓,⅓,⅓), (½,¼,¼), (¼,¼,½) | **A research screen, not investment advice.** Scores are relative to the 481, not absolute quality. |
| Ranks | `rank_Balanced`, `rank_Income-focused`, `rank_Cautious` | Show the rank range across the three weightings, not one "best" list. |
| Top-20 context | 16 distinct rent areas (11 of 20 share rent); 16 above-median crime; 6 with a 3-bed rent marked verify; 15 of 20 saw rent fall over the last 2 years (median −1.4% a year against −0.7% for the rest) | Read the score as past performance next to `rent_change_2y_pa`. |

### Population and community

| Metric | Column (file) | Definition | Caveat to state |
|---|---|---|---|
| Population change | `pop_change_2018_2023_pct` (`master_flagged`) | (2023 ÷ 2018 − 1) × 100 | Blank where 2018 population was 0. Very large values are new subdivisions. |
| Religion, ethnicity shares | `pct_muslim`, `pct_hindu`, `pct_pacific`, … (`master_flagged`); long form in `community_by_sa2`: one row per `group`, share `pct_2023` (also 2013, 2018) | Group ÷ people who stated × 100 | Multi-response: shares can add to more than 100%. Where people **live**, not where facilities are. |
| Community hub | `is_hub` (`community_by_sa2`) | Location quotient (`lq_2023`) ≥ 2 and 300+ members, analysis-ready SA2 | — |
| Concentration | `dissimilarity_2013`, `dissimilarity_2023` (`community_summary`) | Dissimilarity index on the same SA2s in all three census years per community | 0 = spread evenly, 1 = fully separate. |
| Area figures for a community | `area_weighted_*` (`community_summary`) | Median across SA2s weighted by the group's 2023 head count | **"In the areas where members live"**, not what members pay or earn. |
| Islamic schools | `km_to_al_madinah_coed`, `km_to_zayed_college_girls` (`area_profiles_by_sa2`) | Straight-line km from the SA2 centre to Al-Madinah School (composite, co-educational) and Zayed College for Girls (Years 7–15, girls only) | Both are on Westney Road, Māngere, so this is effectively distance to Māngere. Not travel time. |
| Nearest mosque | `km_to_nearest_mosque`, `nearest_mosque` (`area_profiles_by_sa2`) | Straight-line km from the SA2 centre to the nearest of the **6 verified** mosques in `mosques_verified.csv` (street address from the operator or a directory, OpenStreetMap building at that address) | **"From a verified list of 6 mosques; many Auckland mosques are not in it."** Straight-line, not travel time. Median analysis-ready SA2 6.0 km; 24% of residents and 37% of Muslim residents within 3 km (these understate access, since the list is partial). |
| In the area (suburb) | `primary_schools_in_area`, `secondary_schools_in_area`, `year1_schools_in_area`, `mosques_in_area` (`area_profiles_by_sa2`) | Count of facilities **inside the SA2 boundary**. Schools by year levels served: primary = any of Years 1–8, secondary = any of Years 9–13 (a composite school counts as both), Year 1 = takes Year 1 | Answers "is there one in this suburb?". A zero is common (of 599 analysis-ready SA2s: 258 no primary, 501 no secondary, 274 no Year 1 school, 593 no verified mosque) and does not mean far away: then give the nearest by name and distance. For mosques a zero reads "no mosque from the verified list falls inside this SA2". |
| GP practices | `gp_clinics_in_area`, `nearest_gp_clinic`, `km_to_nearest_gp_clinic` (`area_profiles_by_sa2`) | OSM doctors' surgeries (and clinics named like a medical centre or A&M), specialists excluded by tag or name | **"From OpenStreetMap, which may be incomplete."** A zero means none mapped. Name rules can let a non-GP clinic through. Says nothing about whether a practice takes new patients. Median SA2 0.9 km to the nearest; 432 of 599 have none inside. |
| Halal food | `halal_butchers_in_area`, `nearest_halal_butcher`, `km_to_nearest_halal_butcher`, `halal_places_in_area` (`area_profiles_by_sa2`) | OSM places tagged `diet:halal` yes/only or with "halal" in the name; butchers = shop=butcher or "meat"/"butcher" in the name | **"From OpenStreetMap, which may be incomplete."** Only 17 butchers mapped (median SA2 4.9 km to the nearest). `halal_places_in_area` is mostly restaurants and takeaways. Not a certification check. |
| Playgrounds | `playgrounds_in_area`, `nearest_playground`, `km_to_nearest_playground` (`area_profiles_by_sa2`) | OSM `leisure=playground` (points and areas), public only: tagged private, no access or customers-only dropped (school, childcare, fast-food) | **"From OpenStreetMap, which may be incomplete."** A zero means none mapped. Most have no name: `nearest_playground` reads "Playground in <park>" or "(unnamed playground)". Equipment, age range and fencing not in the data. Of 599 analysis-ready SA2s, 103 have none mapped inside; median 0.3 km to the nearest. |
| Parks | `parks_in_area`, `nearest_park`, `km_to_nearest_park` (`area_profiles_by_sa2`) | OSM `leisure=park`, public only (as above) | **"From OpenStreetMap, which may be incomplete."** A park counts once whatever its size (size in `parks_auckland.csv`, `area_ha`); 763 of 3,320 are unnamed. 30 of 599 analysis-ready SA2s have none mapped inside; median 0.2 km to the nearest. |
| Supermarkets | `supermarkets_in_area`, `nearest_supermarket`, `km_to_nearest_supermarket` (`area_profiles_by_sa2`) | OSM `shop=supermarket` whose brand or name is Woolworths (or the old Countdown), New World, PAK'nSAVE, FreshChoice or SuperValue; same store within ~100 m counted once | **"Main chains only, from OpenStreetMap, which may be incomplete."** A zero means none mapped. `nearest_supermarket` is the chain plus OSM branch where tagged ("Woolworths Westgate"); 37 stores have no branch tag and read as the chain only, so always give the distance with it. Independent and ethnic grocers are not counted. Of 599 analysis-ready SA2s, 518 have none inside; median 1.1 km to the nearest. |
| Shopping centres | `shopping_centres_in_area`, `nearest_shopping_centre`, `km_to_nearest_shopping_centre` (`area_profiles_by_sa2`) | OSM `shop=mall`, named and mapped as a site of 0.5 ha or more (points and small sites were mostly single shops, clinics or arcades); City Works Depot dropped (food precinct) | **"Larger shopping centres from OpenStreetMap, which may miss some."** A zero means none mapped. Of 599 analysis-ready SA2s, 578 have none inside; median 2.4 km to the nearest. |
| Nearest Year 1 school | `nearest_year1_school`, `km_to_nearest_year1_school`, `nearest_year1_school_authority`, `nearest_year1_school_enrolment_scheme` (`area_profiles_by_sa2`) | Nearest school taking Year 1, its authority (State, State : Integrated, Private, Charter) and whether it has an enrolment scheme (home zone) | Nearest is not the zoned school; a private or integrated school has fees or entry criteria. |
| Nearest school | `nearest_primary_school`, `km_to_nearest_primary_school`, `nearest_secondary_school`, `km_to_nearest_secondary_school` (`area_profiles_by_sa2`) | Open MoE school of that level nearest the SA2 centre, straight-line km | Not the school zone: a home may be zoned for a different school. Can sit outside the SA2 even when the count inside is above 0. |
| Schools and stops nearby | `primary_schools_2km`, `secondary_schools_3km`, `pt_stops_800m` (`area_profiles_by_sa2`) | Counts within the radius of the SA2 centre | Ignores school zones and service frequency. |

### Rent forecast (File 8, `rent_forecast_by_sa2.csv`)

| Item | Rule | Caveat to state |
|---|---|---|
| Forecast rent | `forecast_rent_y1` (year to Sep 2027, `year1_period`), `forecast_rent_y2` (year to Sep 2028); mean new-tenancy rent over that year | **"Forecast: Auckland's damped rent trend applied to this area's current rent."** Every area gets the same % (`change_y1_pct` −0.3%, `change_y2_pct` −0.6%): area-specific growth did not beat it in the backtest. |
| Band | `y1_low`–`y1_high`, `y2_low`–`y2_high`: 80% band from the model's errors over 13 tests (2012–2024), wider where `flag_thin_sample` (under 30 new bonds in 4 quarters, 36 rent areas) | Always show the band and period with the number. 1 area in 5 lands outside. |
| Accuracy | Trained to Sep 2024: 5.0% mean error for the year to Sep 2025, 6.2% for the year to Sep 2026 (`rent_forecast_backtest.csv`) | "About 5% typical error in a one-year test." The model expected +0.9% / +2.0% Auckland-wide; actual was −0.1% / −0.9%. |
| Sharing | Areas with `flag_borrowed_rent` share the forecast of their rent area; `is_new_development` areas forecast from the 2018 parent area | — |

### Family screen (File 3)

| Item | Rule |
|---|---|
| Budget filter | Caps the rent of the requested dwelling type and bedrooms (`rent_by_type_sa2`), never the all-dwelling median. |
| Result status | `ok` = passes both sample checks; `verify` = thin or unstable, needs a second source (Tenancy Services market rent tool or listings) before it is called a match; `no estimate` = no published rent, neither in nor out. |
| Reporting | Always say how many SA2s pass the other filters, how many lack an estimate, and how many distinct rent areas the matches use. |
| Reference result | 3-bed house under $580/wk: 4 under budget on 2 rent areas, all `verify`, **none confirmed**; 138 no estimate. Cheapest `ok` 3-bed house estimates start at about $608 (Pukekohe). |

## Auckland headline figures

| Figure | Value | Source and definition |
|---|---|---|
| Auckland median weekly rent | **$643** | MBIE official monthly series, mean of the Jul, Aug, Sep 2026 monthly medians ($640, $650, $640). Use this, not an average of SA2 medians (which runs about $18 higher). |
| Census rent paid, Auckland | **$540** | Stats NZ published 2023 Census median, all renting households |
| New-tenancy rent at census time | **$603** | Mean of six MBIE monthly medians, Oct 2022 – Mar 2023. Gap against $540: +11.7% ($63/wk) |
| Typical SA2 rent gap | **+11.2% ($64/wk)** | 305 SA2s with 30+ new lodgements; +7.1% ($48) where under 5% of renters are in social housing |
| Median SA2 CV change 2021–24 | **−8.57%** | 599 analysis-ready SA2s; 56 rose |
| Median area rent-to-income ratio | **29.4%** | Area-level, not rental stress |
| Population 2023 | **1,656,417** | Stats NZ 2023 Census |
| Muslim residents 2023 | **48,108 (2.9%)** | Stats NZ 2023 Census, religious affiliation |
| Auckland median sale price | **$965,000 (2025 Q4)** | HUD, latest complete quarter. Peak $1,207,000 in 2021 Q4: median −20%, price index −24%, real −32% since |
| Rent since the price peak | **+8.8%** | MBIE quarterly mean of monthly medians, 2021 Q4 → 2025 Q4, while the HUD price index fell 24% |
| Auckland sales a year | **23.9k (2025)** | HUD; 34.3k in 2021, 19.4k in 2022 |
| COVID rent dip | $570 (Apr 2020) → $550 (May); $560 (Jun) → $550 (Jul); $570 by Dec 2020, $600 by Dec 2021 | MBIE monthly series. Rent **did** fall briefly. |

## Never say

- That CV is a sale price or market value.
- That a tenanted property earns X% below market (the File 6 gap compares two populations).
- That rent-to-income measures rental stress or what renters pay.
- That the turnover proxy is an average tenancy length.
- That rent "never fell" during COVID.
- Why rent cooled in 2025 (supply, demand, migration): the data does not show the cause.
- That a `verify` rent is a confirmed budget match.
- That census shares show where mosques, temples, halal shops or faith schools are, or naming such places from general knowledge.
  Mosques may be named only from `nearest_mosque` (the verified register), with its caveat.
- That an SA2 has no mosque: say "no mosque from the verified list falls inside this SA2". That the verified list is complete, or that a distance is travel time.
- That an area has no GP or halal shop when `*_in_area` is 0 (say "none mapped"), that a GP is taking patients, or that a place is halal-certified.
- A suburb or SA2 sale price from this data, or that no local-board price data exists (the ministry's HPI has it; this project doesn't use it), or quoting the provisional quarter as the latest price.
- That a top-ranked SA2 is a good investment (it is a research screen).
- A rent forecast without its band and period, or as certain; that an area's rent will grow faster or slower than another's
  (the forecast applies one Auckland trend); why rent will move (the model has no causes).
- That an area has no playground or park when `*_in_area` is 0 (say "none mapped"), or anything about equipment, age range or safety.
- That an area has no supermarket or shopping centre when `*_in_area` is 0 (say "none mapped"), or opening hours, prices or store size.

## Not in the data

| Question | Why not | Closest available |
|---|---|---|
| Sale prices by suburb or local board | REINZ, QV and CoreLogic are paid; the archived Urban Development TA.csv used here is Auckland-wide (the ministry's local-board HPI exists but is not used) | `median_cv_2024`, `cv_change_2021_2024_pct`; Auckland-wide trend in `auckland_sales_quarterly` |
| Renter household income, rental stress | No income-by-tenure table in the census pull | `rent_to_income_pct` (area-level) |
| A complete list of mosques, prayer rooms, halal shops, GPs | 6 verified mosques from the user's list; OpenStreetMap for GPs and halal food (community-mapped, incomplete) | `*_in_area`, `nearest_*`; point the user to other sources for anything else |
| GP enrolment (taking new patients), halal certification | Not in any source used | — |
| Building consents, future supply by area | Deferred to version 2 (decision 18 Nov) | — |
| Detailed ethnicity (Indian, Chinese, Filipino, …) by SA2 | Not downloaded yet | Broad groups in `community_by_sa2` |
| Flood and land hazards, insurance, rates, body-corporate fees | Not in scope | — |
