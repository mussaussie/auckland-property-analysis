"""Shared data loading and rental search for the dashboard (app.py) and the future AI chat.

No Streamlit here, so the chat can call the same code the manual filters use:
    data = load_data()
    result = rental_search(data, max_rent=600, dwelling="House", beds="3")
Self-check: python search.py
"""
import numpy as np
import pandas as pd

CLEAN = "data/clean"


def _sa2_rows():
    sa2 = pd.read_csv(f"{CLEAN}/master_flagged.csv")
    for f in ["rent_metrics_by_sa2", "area_profiles_by_sa2", "risk_value_screen", "rent_market_by_sa2", "rent_premium_by_sa2",
              "rent_forecast_by_sa2"]:
        d = pd.read_csv(f"{CLEAN}/{f}.csv").rename(columns={"flag_thin_sample": "forecast_thin_sample"})  # only the forecast file has it
        new = [c for c in d.columns if c not in sa2.columns]
        sa2 = sa2.merge(d[["sa2_code"] + new], on="sa2_code", how="left")
    comparable = sa2["analysis_ready"] & ~sa2["flag_crime_hotspot"]
    lo, hi = sa2.loc[comparable, "crime_per_1000_residents"].quantile([1 / 3, 2 / 3])
    sa2["crime_rating"] = np.select([sa2["flag_crime_hotspot"], sa2["crime_per_1000_residents"] <= lo, sa2["crime_per_1000_residents"] <= hi,
                                     sa2["crime_per_1000_residents"] > hi], ["Hotspot", "Low", "Moderate", "High"], default="—")
    sa2.loc[~sa2["analysis_ready"], "crime_rating"] = "—"
    return sa2


def _suburb_rows():
    """build_suburbs.py outputs joined on suburb_id, under the SA2 column names the pages and chat read.
    shortcut: suburb_id/suburb_name are stored as sa2_code/sa2_name so every page works at both levels unchanged;
    rename to area_code/area_name if the SA2 level is ever dropped."""
    s = pd.read_csv(f"{CLEAN}/suburb_profiles.csv")
    for f in ["suburb_screen", "suburb_rent_premium", "suburb_rent_forecast"]:
        d = pd.read_csv(f"{CLEAN}/{f}.csv").rename(columns={"flag_thin_sample": "forecast_thin_sample"})
        s = s.merge(d[["suburb_id"] + [c for c in d.columns if c not in s.columns]], on="suburb_id", how="left")
    s = s.rename(columns={"suburb_id": "sa2_code", "suburb_name": "sa2_name", "median_age_approx": "median_age",
                          "median_personal_income_approx": "median_personal_income", "median_household_income_approx": "median_household_income",
                          "census_median_rent_weekly_approx": "census_median_rent_weekly", "pt_stops_800m_avg": "pt_stops_800m",
                          "s_bonds_in_suburb": "s_bonds_per_sa2",
                          # all-home rent checks: renamed so they don't collide with the per-home columns with_home_rent() adds
                          "lodged_bonds_4q": "lodged_all_4q", "flag_thin_sample": "flag_thin_all", "flag_unstable_rent": "flag_unstable_all"})
    s["sa2_code"] = s["sa2_code"].astype(int)
    for c in ["analysis_ready", "flag_crime_hotspot", "flag_shared_rural_sa2", "flag_shared_rent_area"]:
        s[c] = s[c].fillna(False).astype(bool)
    # 'shares rent figures with a neighbour': a place with no SA2 of its own, or a rent area that also feeds another suburb
    s["flag_borrowed_rent"] = s["flag_shared_rural_sa2"] | s["flag_shared_rent_area"]
    # one key per independent rent figure: the set of MBIE rent areas behind it (suburb_rent_sources.csv, real MBIE ids), so
    # Arkles Bay and Wade Heads, fed by the same area, count once in 'distinct rent areas'
    src = pd.read_csv(f"{CLEAN}/suburb_rent_sources.csv")
    key = src.groupby("suburb_id")["rent_source_sa2"].agg(lambda x: ";".join(map(str, sorted(set(x)))))
    s["rent_source_sa2"] = s["sa2_code"].map(key)
    for c in ["coverage_note", "special_note"]:
        s[c] = s[c].fillna("")
    return s


def load_data(level="suburb"):
    """All clean files for one level, 'suburb' (LINZ suburbs, default) or 'sa2' (Stats NZ SA2 areas), plus the series the
    dashboard draws. Both levels use the same column names (see _suburb_rows), so searches give the same kind of answer."""
    sub = level == "suburb"
    rows = _suburb_rows() if sub else _sa2_rows()
    # Police crime groups: person = assault, harm/endanger, sexual, robbery; property = burglary, theft (the six sum to crime_total)
    rows["crime_person"] = rows[["crime_assault", "crime_harm_or_endanger_persons", "crime_sexual_offences", "crime_robbery"]].sum(axis=1, min_count=1)
    rows["crime_property"] = rows[["crime_burglary", "crime_theft"]].sum(axis=1, min_count=1)
    rows["return_score"] = (rows["value_score"] + rows["growth_score"]) / 2
    rows["risk_level"] = 100 - rows["risk_score"]          # risk_score: 100 = lowest risk
    # independently represented rows: the base for benchmarks, rankings and budget matches (borrowed places are listed apart)
    rows["independent"] = rows["coverage"].ne("borrowed") if sub else True
    by_sa2 = pd.read_csv(f"{CLEAN}/rent_by_type_sa2.csv", dtype={"beds": str})
    if sub:
        by_type = pd.read_csv(f"{CLEAN}/suburb_rent_by_type.csv", dtype={"beds": str}).rename(columns={"suburb_id": "sa2_code"})
        by_type["data_note"] = by_type["beds"].map(by_sa2.dropna(subset=["data_note"]).drop_duplicates("beds").set_index("beds")["data_note"])
        q = pd.read_csv(f"{CLEAN}/suburb_rent_quarterly.csv", dtype={"beds": str}, parse_dates=["quarter"])
        rent_ts = q[(q["dwelling"] == "ALL") & (q["beds"] == "ALL")].rename(columns={"suburb_id": "sa2_code"})
        community = pd.read_csv(f"{CLEAN}/suburb_community.csv").rename(columns={"suburb_id": "sa2_code"})
        for d in (by_type, rent_ts, community):
            d["sa2_code"] = d["sa2_code"].astype(int)
    else:
        by_type, community = by_sa2, pd.read_csv(f"{CLEAN}/community_by_sa2.csv")
        rent_ts = pd.read_csv(f"{CLEAN}/rent_timeseries_by_sa2.csv", parse_dates=["quarter"])
    return dict(
        level=level, sa2=rows, rent_ts=rent_ts, by_type=by_type, community=community,
        rent_m=pd.read_csv(f"{CLEAN}/auckland_rent_monthly.csv", parse_dates=["month"]),
        sales=pd.read_csv(f"{CLEAN}/auckland_sales_quarterly.csv", parse_dates=["quarter_end"]),
        community_akl=pd.read_csv(f"{CLEAN}/community_summary.csv").set_index("group")["pct_2023"],
        # SA2 parts of each suburb (drill-down) and SA2 name -> suburb (chat: someone types an SA2 name)
        sa2_to_suburb=pd.read_csv(f"{CLEAN}/sa2_to_suburb.csv"),
    )


def rent_period(data):
    """Months covered by the area rents: the last 4 quarters, e.g. 'Oct 2025–Sep 2026'."""
    last = data["rent_ts"]["quarter"].max()  # quarter start: 2026-07-01 = Jul-Sep 2026
    return f"{last - pd.DateOffset(months=9):%b %Y}–{last + pd.DateOffset(months=2):%b %Y}"


def with_home_rent(df, data, dwelling, beds):
    """df (SA2 rows) plus the rent for one home (dwelling x beds) and its sample check: ok / verify / no estimate."""
    bt = data["by_type"]
    cols = ["sa2_code", "rent", "rent_min_quarter", "rent_max_quarter", "lodged_bonds_4q", "quarters", "flag_thin_sample", "flag_unstable_rent"]
    r = bt[(bt["dwelling"] == dwelling) & (bt["beds"] == beds)][cols + (["lodged_bonds_4q_in_suburb"] if "lodged_bonds_4q_in_suburb" in bt else [])]
    r = r.rename(columns={"lodged_bonds_4q_in_suburb": "bonds_apportioned"})  # this home's; the profile's column is all homes
    s = df.merge(r, on="sa2_code", how="left")
    s["check"] = "ok"
    s.loc[s["flag_thin_sample"].eq(True) | s["flag_unstable_rent"].eq(True), "check"] = "verify"
    s.loc[s["rent"].isna(), "check"] = "no estimate"
    s["check_note"] = [check_note(r) for _, r in s.iterrows()]
    return s


def check_note(r):
    """Why a rent passes or fails, beside the figure. The 30-bond rule is applied to the MBIE source area's lodgements;
    at suburb level the share apportioned to the suburb is an estimate, shown but not tested (METRIC_RULES)."""
    if pd.isna(r.get("rent")):
        return "No published figure for this home"
    why = [w for w, f in (("thin sample: fewer than 30 new bonds", "flag_thin_sample"),
                          ("unstable: highest quarter over 1.5x the lowest", "flag_unstable_rent")) if r.get(f) == True]  # noqa: E712 (numpy bools)
    n = f"{r['lodged_bonds_4q']:,.0f} source-area bonds"
    if pd.notna(r.get("bonds_apportioned")):
        # a borrowed place's count is its source SA2's share (it has no SA2 of its own), so say whose share it is
        whose = f"its source SA2 ({r['coverage_source_name']})" if r.get("coverage") == "borrowed" else "this suburb"
        n += f"; about {r['bonds_apportioned']:,.1f} apportioned to {whose} (estimate)"
    return ("Fails sample checks (" + "; ".join(why) + f"); {n}") if why else f"Passes sample checks; {n}"


def rental_search(data, max_rent, dwelling="House", beds="3", include_apt=None):
    """Areas for a budget and a home (dwelling: House / Apartment / Flat / ALL; beds: 1-4, 5+, ALL). Rules as File 3 shortlist().

    Returns a dict (one row per SA2 in each DataFrame):
      areas       every area that passes the other filters, with the rent for this home and its check:
                  ok (30+ new rentals and a steady price), verify (thin or jumpy), no estimate (no published rent)
      under       areas whose published rent for this home is within budget (any check)
      matches     budget matches: under budget AND check ok, cheapest first
      fallbacks   areas to investigate: no rent for this home passes the checks, but a broader steady rent
                  (same type any size, else any home; column 'basis') is within budget. Never budget matches.
      cheapest_ok cheapest rent that passes the checks at any budget (NaN if none)
      shared      places with no SA2 of their own (suburb level) under budget, any check: their rent is the whole parent SA2's,
                  so they are listed apart and never counted in under / matches / fallbacks
    Crime hotspots are always left out; apartment and inner-city areas only when include_apt (default: apartment searches).
    """
    include_apt = dwelling == "Apartment" if include_apt is None else include_apt
    ready = data["sa2"][data["sa2"]["analysis_ready"]]
    bt = data["by_type"]
    keep = ~ready["flag_crime_hotspot"] & (include_apt | (ready["area_type"] != "Apartments & inner city"))
    s = with_home_rent(ready[keep], data, dwelling, beds)
    s["under"] = s["rent"] <= max_rent
    under = s[s["under"]]
    # Thin or jumpy figures (e.g. $93 from 6 bonds in one quarter) are not budget matches; the area's steady wider figure is a lead:
    # same home type any size, else any home. That covers all sizes, so it can sit above or below what this home really costs.
    steady = bt[~(bt["flag_thin_sample"].eq(True) | bt["flag_unstable_rent"].eq(True)) & (bt["beds"] == "ALL")]
    wide = pd.concat([steady[steady["dwelling"] == d].assign(basis="All home types, all bedroom counts" if d == "ALL"
                                                             else f"{d}s only, all bedroom counts")
                      for d in dict.fromkeys([dwelling, "ALL"])]).drop_duplicates("sa2_code")
    fb = s[s["check"] == "verify"].merge(wide[["sa2_code", "rent", "lodged_bonds_4q", "basis"]], on="sa2_code", suffixes=("_thin", ""))
    ind = s["independent"]
    fb = fb[fb["independent"] & (fb["rent"] <= max_rent)]
    return dict(areas=s, under=under[under["independent"]], matches=under[under["independent"] & (under["check"] == "ok")].sort_values("rent"),
                fallbacks=fb.sort_values("rent"), cheapest_ok=s.loc[ind & (s["check"] == "ok"), "rent"].min(),
                shared=under[~under["independent"]].sort_values("rent"))


if __name__ == "__main__":
    s = load_data()
    sub = s["sa2"]
    assert sub["sa2_code"].is_unique and len(sub) == 295 and sub["ranked"].eq(True).sum() == 180 and sub["analysis_ready"].sum() == 289
    assert s["rent_ts"]["sa2_code"].isin(sub["sa2_code"]).all() and s["by_type"]["sa2_code"].isin(sub["sa2_code"]).all()
    z = rental_search(s, 700, "House", "3")
    assert len(z["areas"]) and set(z["matches"]["check"]) <= {"ok"} and z["matches"]["rent"].le(700).all()
    assert z["matches"]["independent"].all() and len(z["shared"]) and not z["shared"]["independent"].any()  # borrowed places apart
    ids = sub.set_index("sa2_name")["rent_source_sa2"]
    assert ids["Arkles Bay"] == ids["Wade Heads"] == "114900"  # same MBIE rent area -> one distinct source
    d = load_data("sa2")
    # Reference result (METRIC_RULES.md, Family screen): 3-bed house <= $580 -> 4 under budget on 2 rent areas, none ok, 138 no estimate
    x = rental_search(d, 580, "House", "3")
    assert (len(x["under"]), x["under"]["rent_source_sa2"].nunique(), len(x["matches"]), (x["areas"]["check"] == "no estimate").sum()) == (4, 2, 0, 138)
    assert x["cheapest_ok"] == 607.5
    # Review case: $600 3-bed house -> no matches, 13 areas to investigate on broader rents
    y = rental_search(d, 600, "House", "3")
    assert len(y["matches"]) == 0 and len(y["fallbacks"]) == 13 and y["fallbacks"]["basis"].str.contains("all bedroom counts").all()
    print("search.py self-check passed")
