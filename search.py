"""Shared data loading and rental search for the dashboard (app.py) and the future AI chat.

No Streamlit here, so the chat can call the same code the manual filters use:
    data = load_data()
    result = rental_search(data, max_rent=600, dwelling="House", beds="3")
Self-check: python search.py
"""
import numpy as np
import pandas as pd

CLEAN = "data/clean"


def load_data():
    """All clean SA2 files joined on sa2_code, plus the series the dashboard draws."""
    sa2 = pd.read_csv(f"{CLEAN}/master_flagged.csv")
    for f in ["rent_metrics_by_sa2", "area_profiles_by_sa2", "risk_value_screen", "rent_market_by_sa2", "rent_premium_by_sa2",
              "rent_forecast_by_sa2"]:
        d = pd.read_csv(f"{CLEAN}/{f}.csv").rename(columns={"flag_thin_sample": "forecast_thin_sample"})  # only the forecast file has it
        new = [c for c in d.columns if c not in sa2.columns]
        sa2 = sa2.merge(d[["sa2_code"] + new], on="sa2_code", how="left")
    # Police crime groups: person = assault, harm/endanger, sexual, robbery; property = burglary, theft (the six sum to crime_total)
    sa2["crime_person"] = sa2[["crime_assault", "crime_harm_or_endanger_persons", "crime_sexual_offences", "crime_robbery"]].sum(axis=1, min_count=1)
    sa2["crime_property"] = sa2[["crime_burglary", "crime_theft"]].sum(axis=1, min_count=1)
    comparable = sa2["analysis_ready"] & ~sa2["flag_crime_hotspot"]
    lo, hi = sa2.loc[comparable, "crime_per_1000_residents"].quantile([1 / 3, 2 / 3])
    sa2["crime_rating"] = np.select([sa2["flag_crime_hotspot"], sa2["crime_per_1000_residents"] <= lo, sa2["crime_per_1000_residents"] <= hi,
                                     sa2["crime_per_1000_residents"] > hi], ["Hotspot", "Low", "Moderate", "High"], default="—")
    sa2.loc[~sa2["analysis_ready"], "crime_rating"] = "—"
    sa2["return_score"] = (sa2["value_score"] + sa2["growth_score"]) / 2
    sa2["risk_level"] = 100 - sa2["risk_score"]          # risk_score: 100 = lowest risk
    return dict(
        sa2=sa2,
        rent_m=pd.read_csv(f"{CLEAN}/auckland_rent_monthly.csv", parse_dates=["month"]),
        sales=pd.read_csv(f"{CLEAN}/auckland_sales_quarterly.csv", parse_dates=["quarter_end"]),
        rent_ts=pd.read_csv(f"{CLEAN}/rent_timeseries_by_sa2.csv", parse_dates=["quarter"]),
        by_type=pd.read_csv(f"{CLEAN}/rent_by_type_sa2.csv", dtype={"beds": str}),
        community=pd.read_csv(f"{CLEAN}/community_by_sa2.csv"),
        community_akl=pd.read_csv(f"{CLEAN}/community_summary.csv").set_index("group")["pct_2023"],
    )


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
    Crime hotspots are always left out; apartment and inner-city areas only when include_apt (default: apartment searches).
    """
    include_apt = dwelling == "Apartment" if include_apt is None else include_apt
    ready = data["sa2"][data["sa2"]["analysis_ready"]]
    bt = data["by_type"]
    r = bt[(bt["dwelling"] == dwelling) & (bt["beds"] == beds)][
        ["sa2_code", "rent", "rent_min_quarter", "rent_max_quarter", "lodged_bonds_4q", "quarters", "flag_thin_sample", "flag_unstable_rent"]]
    keep = ~ready["flag_crime_hotspot"] & (include_apt | (ready["area_type"] != "Apartments & inner city"))
    s = ready[keep].merge(r, on="sa2_code", how="left")
    s["check"] = "ok"
    s.loc[s["flag_thin_sample"].eq(True) | s["flag_unstable_rent"].eq(True), "check"] = "verify"
    s.loc[s["rent"].isna(), "check"] = "no estimate"
    s["under"] = s["rent"] <= max_rent
    under = s[s["under"]]
    # Thin or jumpy figures (e.g. $93 from 6 bonds in one quarter) are not budget matches; the area's steady wider figure is a lead:
    # same home type any size, else any home. That covers all sizes, so it can sit above or below what this home really costs.
    steady = bt[~(bt["flag_thin_sample"].eq(True) | bt["flag_unstable_rent"].eq(True)) & (bt["beds"] == "ALL")]
    wide = pd.concat([steady[steady["dwelling"] == d].assign(basis="All home types, all bedroom counts" if d == "ALL"
                                                             else f"{d}s only, all bedroom counts")
                      for d in dict.fromkeys([dwelling, "ALL"])]).drop_duplicates("sa2_code")
    fb = s[s["check"] == "verify"].merge(wide[["sa2_code", "rent", "lodged_bonds_4q", "basis"]], on="sa2_code", suffixes=("_thin", ""))
    return dict(areas=s, under=under, matches=under[under["check"] == "ok"].sort_values("rent"),
                fallbacks=fb[fb["rent"] <= max_rent].sort_values("rent"), cheapest_ok=s.loc[s["check"] == "ok", "rent"].min())


if __name__ == "__main__":
    d = load_data()
    # Reference result (METRIC_RULES.md, Family screen): 3-bed house <= $580 -> 4 under budget on 2 rent areas, none ok, 138 no estimate
    x = rental_search(d, 580, "House", "3")
    assert (len(x["under"]), x["under"]["rent_source_sa2"].nunique(), len(x["matches"]), (x["areas"]["check"] == "no estimate").sum()) == (4, 2, 0, 138)
    assert x["cheapest_ok"] == 607.5
    # Review case: $600 3-bed house -> no matches, 13 areas to investigate on broader rents
    y = rental_search(d, 600, "House", "3")
    assert len(y["matches"]) == 0 and len(y["fallbacks"]) == 13 and y["fallbacks"]["basis"].str.contains("all bedroom counts").all()
    print("search.py self-check passed")
