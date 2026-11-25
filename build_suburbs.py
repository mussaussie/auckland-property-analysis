"""Map each SA2 to a LINZ suburb (step 1 of suburb results). Later steps aggregate SA2 measures per suburb.

Run after download_data.py and build_master.py:  python build_suburbs.py
"""
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
CLEAN = DATA / "clean"
# Reviewed 26 Nov 2026 (data/boundaries/sa2_to_suburb_review.csv). An override needs census residents (2023 SA1 counts,
# split by where rating units sit) to disagree with the rating-unit pick AND council address labels to agree with the
# residents. Address labels alone never decide.
OVERRIDES = {  # sa2_code: (suburb, boundary_confidence, reason)
    157200: ("Ōtara", "low", "Rongomai East: units near tie (Flat Bush 47.7 / Ōtara 45.8); residents Ōtara 50.3 / Flat Bush 46.1; "
                             "council addresses 95% Ōtara"),
    158603: ("Flat Bush", "medium", "Ormiston South East: residents Flat Bush 65.4 / Tōtara Park 34.6 against units Tōtara Park 53.7; "
                                    "council addresses 99% Flat Bush; 3 of 6 SA1s split by the LINZ line"),
}
EXCLUDED = {  # sa2_code: reason; kept in the lookup with no suburb
    110300: "Water SA2: no census population published, no SA1 residents; units scattered on islands and moorings",
    110600: "Water SA2: no census population published, no SA1 residents; units scattered on islands and moorings",
    111000: "Water SA2: no census population published, no SA1 residents; units scattered on islands and moorings",
    112001: "Water SA2: no census population published, no SA1 residents; units scattered on islands and moorings",
    141400: "Water SA2: no census population published, no SA1 residents; units scattered on islands and moorings",
    119301: "Water SA2: 3 census residents in 2023 (84 in 2018, likely living on boats); 30 units spread over 17 suburbs "
            "(largest 16.7%), so no suburb represents it",
}


def load_layers():
    # NZTM (metres); make_valid repairs the few self-intersecting polygons in both files
    sa2 = gpd.read_file(DATA / "boundaries" / "auckland_sa2_2023.geojson").to_crs(2193)
    sa2 = sa2.rename(columns={"SA22023_V1_00": "sa2_code", "SA22023_V1_00_NAME": "sa2_name"})[["sa2_code", "sa2_name", "geometry"]]
    sa2["sa2_code"] = sa2.sa2_code.astype(int)
    sub = gpd.read_file(DATA / "boundaries" / "auckland_suburbs_linz.geojson").to_crs(2193)
    sub = sub.rename(columns={"id": "suburb_id", "name": "suburb_name", "type": "suburb_type"})[
        ["suburb_id", "suburb_name", "suburb_type", "population_estimate", "geometry"]]
    sa2["geometry"], sub["geometry"] = sa2.make_valid(), sub.make_valid()
    return sa2, sub


def unit_pieces(sa2, sub):
    """Rating units per SA2 x suburb piece. Units stand in for where people live (land area put Waiake in Torbay)."""
    cv = pd.read_csv(DATA / "property_prices" / "auckland_cv_2021_2024.csv", usecols=["lon", "lat"]).dropna()
    pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(cv.lon, cv.lat), crs=4326).to_crs(2193)
    pts = gpd.sjoin(pts, sa2[["sa2_code", "geometry"]], predicate="within").drop(columns="index_right")
    pts = gpd.sjoin(pts, sub[["suburb_id", "geometry"]], predicate="within")
    return pts.groupby(["sa2_code", "suburb_id"]).size().rename("units").reset_index()


def sa2_to_suburb(sa2, sub, units):
    """One row per SA2: the suburb holding most of its rating units (area share only where an SA2 has no units)."""
    area = gpd.overlay(sa2.assign(sa2_area=sa2.area), sub[["suburb_id", "geometry"]], how="intersection", keep_geom_type=True)
    area["area_pct"] = area.area / area.sa2_area * 100
    p = area[["sa2_code", "suburb_id", "area_pct"]].merge(units, on=["sa2_code", "suburb_id"], how="outer")
    p["units"] = p.units.fillna(0)
    p["units_in_sa2"] = p.groupby("sa2_code").units.transform("sum")
    p["unit_pct"] = (p.units / p.units_in_sa2 * 100).where(p.units_in_sa2 > 0)
    p["match_basis"] = p.units_in_sa2.gt(0).map({True: "rating_units", False: "area"})
    p["match_pct"] = p.unit_pct.fillna(p.area_pct).fillna(0).round(1)
    p = p.merge(sub[["suburb_id", "suburb_name", "suburb_type"]], on="suburb_id")
    p["override"] = [OVERRIDES.get(c, (None,))[0] == s for c, s in zip(p.sa2_code, p.suburb_name)]
    assert p.override.sum() == len(OVERRIDES), "each override names a suburb the SA2 overlaps"
    best = p.sort_values(["override", "match_pct", "area_pct"], ascending=False).drop_duplicates("sa2_code")
    best["match_rule"] = best.override.map({True: "reviewed_override", False: "most_units"})
    n = p[p.match_pct > 0].groupby("sa2_code").size().rename("suburbs_overlapped")

    out = sa2[["sa2_code", "sa2_name"]].merge(best[["sa2_code", "suburb_id", "suburb_name", "suburb_type", "match_basis",
                                                     "match_rule", "match_pct", "units_in_sa2"]], on="sa2_code", how="left").join(n, on="sa2_code")
    out["exclusion_reason"] = out.sa2_code.map(EXCLUDED)
    ex = out.exclusion_reason.notna()
    out.loc[ex, ["suburb_id", "suburb_name", "suburb_type", "match_pct"]] = None
    out.loc[ex, "match_rule"] = "excluded"
    out["unmapped"] = out.suburb_id.isna()
    out["units_in_sa2"] = out.units_in_sa2.fillna(0).astype(int)
    out["suburbs_overlapped"] = out.suburbs_overlapped.fillna(0).astype(int)
    out["straddles_suburbs"] = ~out.unmapped & (out.match_pct < 60)

    rv = pd.read_csv(DATA / "boundaries" / "sa2_to_suburb_review.csv", encoding="utf-8-sig")
    out = out.merge(rv[["sa2_code", "boundary_confidence"]], on="sa2_code", how="left")
    out["boundary_confidence"] = out.boundary_confidence.fillna("not reviewed (60%+ of units in one suburb)")
    out["override_reason"] = out.sa2_code.map({c: r for c, (_, _, r) in OVERRIDES.items()})
    for c, (_, conf, _) in OVERRIDES.items():
        out.loc[out.sa2_code == c, "boundary_confidence"] = conf

    assert out.sa2_code.is_unique and len(out) == len(sa2), "one row per SA2"
    assert out.unmapped.sum() == len(EXCLUDED), "only the reviewed exclusions are unmapped"
    # the build must reproduce every reviewed decision
    chk = rv.merge(out[["sa2_code", "suburb_name"]], on="sa2_code")
    want = chk.suggested_suburb.where(chk.suggested_suburb != "(none)")
    bad = chk[~((want == chk.suburb_name) | (want.isna() & chk.suburb_name.isna()))]
    assert bad.empty, bad[["sa2_name", "suggested_suburb", "suburb_name"]]
    return out.sort_values("sa2_code"), p[~p.sa2_code.isin(EXCLUDED)]


def suburb_list(sub, lookup, pieces, pop):
    """One row per suburb with residents. Places that hold no SA2 of their own reuse the SA2 most of their units sit in,
    flagged like flag_borrowed_rent: totals and rankings count each source SA2 once."""
    lookup = lookup.merge(pop, on="sa2_code", how="left")
    main = lookup.dropna(subset=["suburb_id"]).groupby("suburb_id").agg(
        sa2_codes=("sa2_code", lambda s: ";".join(map(str, sorted(s)))), n_sa2=("sa2_code", "size"),
        population_2023=("population_2023", "sum")).reset_index()
    main["suburb_source_sa2"] = pd.NA

    inhabited = sub[sub.population_estimate.fillna(0) > 0]
    extra = inhabited[~inhabited.suburb_id.isin(main.suburb_id)]
    parent = (pieces[pieces.suburb_id.isin(extra.suburb_id)].assign(w=lambda d: d.units.where(d.units > 0, d.area_pct / 1e6))
              .sort_values("w", ascending=False).drop_duplicates("suburb_id")[["suburb_id", "sa2_code"]])
    shared = parent.rename(columns={"sa2_code": "suburb_source_sa2"}).merge(
        pop.rename(columns={"sa2_code": "suburb_source_sa2"}), on="suburb_source_sa2", how="left")
    shared["sa2_codes"], shared["n_sa2"] = shared.suburb_source_sa2.astype(str), 0

    out = pd.concat([main, shared], ignore_index=True).merge(
        sub[["suburb_id", "suburb_name", "suburb_type", "population_estimate"]], on="suburb_id")
    # mirror of flag_borrowed_rent: every row that uses an SA2 also used by a shared row, the parent included
    used = set(shared.suburb_source_sa2)
    out["flag_shared_rural_sa2"] = out.sa2_codes.str.split(";").map(lambda c: bool(used & {int(x) for x in c}))
    out["caveat"] = out.flag_shared_rural_sa2.map({True: "Shares figures with neighbouring localities: the data covers the whole "
                                                         "statistical area, not this place alone.", False: ""})
    # dedup check: counting each source SA2 once must give the Auckland total, less the excluded water SA2s
    assert out[out.suburb_source_sa2.isna()].population_2023.sum() == lookup[~lookup.unmapped].population_2023.sum()
    assert lookup[~lookup.unmapped].population_2023.sum() == pop.population_2023.sum() - pop[pop.sa2_code.isin(EXCLUDED)].population_2023.sum()
    cols = ["suburb_id", "suburb_name", "suburb_type", "n_sa2", "sa2_codes", "suburb_source_sa2", "flag_shared_rural_sa2",
            "caveat", "population_2023", "population_estimate"]
    return out[cols].sort_values("suburb_name")


def members(lookup, subs):
    """suburb_id x sa2_code. Own-SA2 suburbs list their SA2s; shared places list their parent SA2 (main=False),
    so every figure uses one code path and totals sum main rows only (each SA2 once)."""
    own = lookup.dropna(subset=["suburb_id"])[["suburb_id", "sa2_code"]].assign(main=True)
    shared = subs.dropna(subset=["suburb_source_sa2"])[["suburb_id", "suburb_source_sa2"]].rename(
        columns={"suburb_source_sa2": "sa2_code"}).assign(main=False)
    m = pd.concat([own, shared], ignore_index=True)
    m["sa2_code"] = m.sa2_code.astype(int)
    return m


def wmean(df, value, weight, by="suburb_id"):
    """Weighted mean of SA2 values; labelled approximate wherever it stands in for a median."""
    d = df.dropna(subset=[value, weight])
    return (d[value] * d[weight]).groupby(d[by]).sum() / d[weight].groupby(d[by]).sum()


def nearest(df, km, cols):
    """Smallest distance over the parts, with the name (and details) from that part."""
    return df.dropna(subset=[km]).sort_values(km).drop_duplicates("suburb_id").set_index("suburb_id")[[km] + cols]


def core_figures(mem):
    """Stage A: census, CV, crime, amenities and flags per suburb, with the combining rule per measure."""
    import build_master as bm
    master = pd.read_csv(CLEAN / "master_flagged.csv")
    ap = pd.read_csv(CLEAN / "area_profiles_by_sa2.csv")
    sa = mem.merge(master, on="sa2_code").merge(ap[["sa2_code"] + [c for c in ap.columns if c not in master.columns]], on="sa2_code")
    g = sa.groupby("suburb_id")

    # census: sum the raw counts, then the same share formulas as build_master (exact, not averages of shares)
    cc = bm.census_counts()
    cc.index = cc.index.astype(int)
    counts = [c for c in cc.columns if c.startswith("_") or c in ("population_2018", "population_2023", "households_2023", "dwellings_2023")]
    out = bm.census_shares(mem.merge(cc[counts], left_on="sa2_code", right_index=True).groupby("suburb_id")[counts].sum(min_count=1))
    # medians cannot be combined exactly: weighted mean of the SA2 medians, marked approximate in the column name
    sa["rented_households"] = sa.households_2023 * (1 - sa.pct_owner_occupied.fillna(0) / 100)
    for col, w in [("median_age", "population_2023"), ("median_personal_income", "population_2023"),
                   ("median_household_income", "households_2023"), ("census_median_rent_weekly", "rented_households"),
                   ("avg_bedrooms", "dwellings_2023")]:
        out[f"{col}_approx"] = wmean(sa, col, w)
    out["land_area_sq_km"] = g.land_area_sq_km.sum()

    # capital values: a true median of the rating units inside the suburb's SA2s (not an average of SA2 medians)
    sa2 = gpd.read_file(DATA / "boundaries" / "auckland_sa2_2023.geojson").rename(columns={"SA22023_V1_00": "sa2_code"})
    cv = pd.read_csv(DATA / "property_prices" / "auckland_cv_2021_2024.csv", usecols=["CV", "LCV", "LLV", "lon", "lat"])
    cv = pd.DataFrame(bm.by_sa2(bm.points(cv, "lon", "lat"), sa2).drop(columns="geometry"))
    cv = mem.merge(cv.assign(sa2_code=cv.sa2_code.astype(int)), on="sa2_code").groupby("suburb_id")
    out["rating_units"] = cv.size()
    out["median_cv_2021"], out["median_cv_2024"], out["median_land_value_2024"] = cv.CV.median(), cv.LCV.median(), cv.LLV.median()
    out["cv_change_2021_2024_pct"] = 100 * (out.median_cv_2024 / out.median_cv_2021 - 1)
    out["land_share_of_cv_pct"] = 100 * out.median_land_value_2024 / out.median_cv_2024

    # crime: summed counts over summed residents (same 100-resident and 300 hotspot rules as the SA2 file)
    crime = [c for c in master.columns if c.startswith("crime_") and c != "crime_per_1000_residents"]
    out[crime] = g[crime].sum()
    out["crime_per_1000_residents"] = 1000 * out.crime_total / out.population_2023.where(out.population_2023 >= 100)

    # amenities: counts inside the area add up; "within x km" counts are measured from each SA2, so residents' average
    inside = ["schools", "pt_stops"] + [c for c in ap.columns if c.endswith("_in_area")]
    out[inside] = g[inside].sum()
    for col in ["primary_schools_2km", "secondary_schools_3km", "pt_stops_800m"]:
        out[f"{col}_avg"] = wmean(sa, col, "population_2023")
    for km, cols in [("km_to_nearest_primary_school", ["nearest_primary_school"]),
                     ("km_to_nearest_secondary_school", ["nearest_secondary_school"]),
                     ("km_to_nearest_year1_school", ["nearest_year1_school", "nearest_year1_school_authority",
                                                     "nearest_year1_school_enrolment_scheme"]),
                     ("km_to_nearest_mosque", ["nearest_mosque"]), ("km_to_nearest_gp_clinic", ["nearest_gp_clinic"]),
                     ("km_to_nearest_halal_butcher", ["nearest_halal_butcher"]), ("km_to_nearest_playground", ["nearest_playground"]),
                     ("km_to_nearest_park", ["nearest_park"]), ("km_to_nearest_supermarket", ["nearest_supermarket"]),
                     ("km_to_nearest_shopping_centre", ["nearest_shopping_centre"]),
                     ("km_to_al_madinah_coed", []), ("km_to_zayed_college_girls", [])]:
        out = out.join(nearest(sa, km, cols))

    # flags: the SA2 rules (METHODOLOGY 5) applied to the suburb's own totals
    out["units_per_dwelling"] = out.rating_units / out.dwellings_2023
    out["flag_low_population"] = out.population_2023.fillna(0) < 100
    out["flag_non_residential"] = (out.units_per_dwelling > 2) | (out.dwellings_2023.fillna(0) < 30)
    out["analysis_ready"] = ~out.flag_non_residential & ~out.flag_low_population
    out["flag_crime_hotspot"] = out.crime_per_1000_residents > 300
    return out


def load_rent_by_type():
    """Raw MBIE quarterly rows for every dwelling type x bedrooms (build_master keeps ALL x ALL only)."""
    cols = ["TimeFrame", "Location Id", "Dwelling Type", "Number Of Beds", "Median Rent", "Active Bonds", "Total Bonds",
            "Closed Bonds", "Lower Quartile Rent", "Upper Quartile Rent"]
    r = pd.concat([pd.read_csv(DATA / "rental" / f, usecols=cols, dtype=str)
                   for f in ["mbie_quarterly_sa2_1993_2019.zip", "mbie_quarterly_sa2_2020_2026.csv"]])
    r = r[pd.to_numeric(r["Location Id"], errors="coerce") > 0]
    num = {c: pd.to_numeric(r[c], errors="coerce") for c in cols[4:]}
    return pd.DataFrame({"rent_source_sa2": r["Location Id"].astype(float).astype(int), "quarter": pd.to_datetime(r.TimeFrame, dayfirst=True),
                         "dwelling": r["Dwelling Type"], "beds": r["Number Of Beds"], "median_rent": num["Median Rent"],
                         "active_bonds": num["Active Bonds"], "lodged_bonds": num["Total Bonds"], "closed_bonds": num["Closed Bonds"],
                         "lq_rent": num["Lower Quartile Rent"], "uq_rent": num["Upper Quartile Rent"]})


def rent_area_shares(mem):
    """Share of each MBIE rent area that lies in each suburb, by rented households (MBIE bonds cover rented homes).
    A rent area split across suburbs gives each suburb its full median but only its share of the bonds."""
    master = pd.read_csv(CLEAN / "master_flagged.csv", usecols=["sa2_code", "rent_source_sa2", "households_2023", "pct_owner_occupied"])
    master["rented"] = (master.households_2023 * (1 - master.pct_owner_occupied.fillna(0) / 100)).fillna(0)
    s = mem.merge(master.dropna(subset=["rent_source_sa2"]), on="sa2_code")
    area_total = master.dropna(subset=["rent_source_sa2"]).groupby("rent_source_sa2").rented.sum()
    s = s.groupby(["suburb_id", "rent_source_sa2", "main"]).rented.sum().reset_index()
    s["rent_source_sa2"] = s.rent_source_sa2.astype(int)
    s["share"] = (s.rented / s.rent_source_sa2.map(area_total)).fillna(0)
    return s[["suburb_id", "rent_source_sa2", "main", "share"]]


def suburb_rent_quarterly(raw, shares):
    """Each quarter, dwelling and bedrooms: suburb median = mean of its rent areas' medians weighted by the bonds
    lodged that quarter in the suburb's share of each area (unweighted where no bonds are recorded)."""
    q = shares.merge(raw.dropna(subset=["median_rent"]), on="rent_source_sa2")
    q["w"] = q.lodged_bonds.fillna(0) * q.share
    k = ["suburb_id", "dwelling", "beds", "quarter"]
    q["wsum"] = q.groupby(k).w.transform("sum")
    q["w"] = q.w.where(q.wsum > 0, 1.0)
    for c in ["median_rent", "lq_rent", "uq_rent"]:
        q[c + "_w"] = q[c] * q.w
    q["w_lq"], q["w_uq"] = q.w.where(q.lq_rent.notna()), q.w.where(q.uq_rent.notna())
    for c in ["active_bonds", "lodged_bonds", "closed_bonds"]:
        q[c + "_in_suburb"] = q[c] * q.share
    a = q.groupby(k).agg(m=("median_rent_w", "sum"), w=("w", "sum"), lq=("lq_rent_w", "sum"), wlq=("w_lq", "sum"),
                         uq=("uq_rent_w", "sum"), wuq=("w_uq", "sum"), lodged_full=("lodged_bonds", "sum"),
                         lodged=("lodged_bonds_in_suburb", "sum"), active=("active_bonds_in_suburb", "sum"),
                         closed=("closed_bonds_in_suburb", "sum"), rent_areas=("rent_source_sa2", "nunique")).reset_index()
    a["median_rent"], a["lq_rent"], a["uq_rent"] = a.m / a.w, a.lq / a.wlq.where(a.wlq > 0), a.uq / a.wuq.where(a.wuq > 0)
    return a.drop(columns=["m", "w", "lq", "wlq", "uq", "wuq"])


def rent_by_type(qs):
    """Last 4 quarters per suburb x dwelling x bedrooms, with File 2's sample checks (30+ new bonds, steady price)."""
    latest = qs.quarter.max()
    y = qs[qs.quarter > latest - pd.DateOffset(years=1)]
    g = y.groupby(["suburb_id", "dwelling", "beds"])
    t = g.agg(rent=("median_rent", "mean"), quarters=("median_rent", "size"), rent_min_quarter=("median_rent", "min"),
              rent_max_quarter=("median_rent", "max"), lodged_bonds_4q=("lodged_full", "sum"),
              lodged_bonds_4q_in_suburb=("lodged", "sum"), rent_areas=("rent_areas", "max")).reset_index()
    t = t.merge(y.sort_values("quarter").groupby(["suburb_id", "dwelling", "beds"]).active.last().rename("active_bonds_in_suburb").reset_index())
    t["flag_thin_sample"] = ~(t.lodged_bonds_4q >= 30)
    t["flag_unstable_rent"] = t.rent_max_quarter > 1.5 * t.rent_min_quarter
    t["rent_note"] = "Approximate: lodgement-weighted mean of MBIE rent-area medians; MBIE publishes no suburb median."
    return t


def rent_trends(qs):
    """Stage B: File 2, 4 and 5 rent-over-time measures, same formulas, on the suburb's quarterly series (all dwellings)."""
    ts = qs[(qs.dwelling == "ALL") & (qs.beds == "ALL")]
    latest = ts.quarter.max()

    def window(years_back, col="median_rent", how="mean"):  # 4 quarters ending N years before the latest quarter
        end = latest - pd.DateOffset(years=years_back)
        return ts[(ts.quarter > end - pd.DateOffset(years=1)) & (ts.quarter <= end)].groupby("suburb_id")[col].agg(how)

    now = window(0)
    t = pd.DataFrame({f"rent_{n}y_ago": window(n) for n in [1, 5, 10]})
    for n in [1, 5, 10]:
        t[f"rent_change_{n}y_pct"] = 100 * (now / t[f"rent_{n}y_ago"] - 1)
    t["rent_cagr_10y_pct"] = 100 * ((now / t.rent_10y_ago) ** (1 / 10) - 1)
    r6, r2 = window(6), window(2)
    t["boom_pa"] = 100 * ((r2 / r6) ** (1 / 4) - 1)
    t["cooling_pa"] = 100 * ((now / r2) ** (1 / 2) - 1)
    t["rent_change_2y_pa"] = t.cooling_pa  # File 4 shows File 5's cooling rate under this name

    p = ts.pivot(index="quarter", columns="suburb_id", values="median_rent")
    p = p.reindex(pd.date_range(p.index.min(), p.index.max(), freq="QS"))  # blank quarters stay blank: pct_change(4) = one year
    yoy = 100 * p.pct_change(4, fill_method=None)
    yoy = yoy[yoy.index > yoy.index.max() - pd.DateOffset(years=10)]
    t["rent_volatility"] = yoy.std().where(yoy.notna().sum() >= 20)

    y = ts[ts.quarter > latest - pd.DateOffset(years=1)].groupby("suburb_id")
    full = y.size() == 4  # a full year only, so turnover isn't understated
    t["turnover_pct"] = (100 * y.closed.sum() / y.active.mean()).where(full)
    t["rent_spread"] = (y.uq_rent.mean() / y.lq_rent.mean()).where(full)
    return t


def area_type(mem):
    """File 3 type covering most of the suburb's residents (k-means types exist per SA2 only), with that share."""
    sa = mem.merge(pd.read_csv(CLEAN / "area_profiles_by_sa2.csv", usecols=["sa2_code", "area_type", "population_2023"]), on="sa2_code")
    by = sa.dropna(subset=["area_type"]).groupby(["suburb_id", "area_type"]).population_2023.sum().reset_index()
    top = by.sort_values("population_2023", ascending=False).drop_duplicates("suburb_id").set_index("suburb_id")
    tot = sa.groupby("suburb_id").population_2023.sum()
    return pd.DataFrame({"area_type": top.area_type, "area_type_share_pct": 100 * top.population_2023 / tot})


def screen(prof):
    """File 4 risk & value screen re-scored across suburbs: same universe, seven measures, complete-input rule and profiles.
    Market depth = active bonds apportioned to the suburb (File 4's bonds_per_sa2 rule). Shared-SA2 rows are not ranked:
    their figures belong to the parent SA2's suburb, so ranking them would count that SA2 twice."""
    m = prof[prof.suburb_source_sa2.isna()].copy()
    m["bonds_in_suburb"] = m.active_bonds_in_suburb
    fast = m.pop_change_2018_2023_pct > 100
    m["is_new_development"] = fast & m.flag_shared_rent_area  # suburb version of 'doubled and borrows a shared rent series'
    m["flag_rapid_growth"] = fast & ~m.flag_shared_rent_area
    u = m[m.analysis_ready.fillna(False).astype(bool) & ~m.flag_crime_hotspot.fillna(False).astype(bool)
          & (m.pct_separate_house >= 50) & m.median_rent_weekly.notna() & m.median_cv_2024.notna()].copy()
    measures = [("gross_yield_pct", "value", True), ("rent_cagr_10y_pct", "growth", True),
                ("pop_change_2018_2023_pct", "growth", True), ("crime_per_1000_residents", "risk", False),
                ("rent_volatility", "risk", False), ("cv_change_2021_2024_pct", "risk", True), ("bonds_in_suburb", "risk", True)]
    cols = [c for c, _, _ in measures]
    u["missing_inputs"] = u[cols].isna().apply(lambda r: ", ".join(r.index[r]), axis=1)
    ok = (u.missing_inputs == "") & ~u.is_new_development
    r = u[ok].copy()
    for c, _, hb in measures:
        r[f"s_{c}"] = r[c].rank(pct=True, ascending=hb) * 100
    for g in ["value", "growth", "risk"]:
        r[f"{g}_score"] = r[[f"s_{c}" for c, gg, _ in measures if gg == g]].mean(axis=1)
    for name, (wv, wg, wr) in {"Balanced": (1 / 3, 1 / 3, 1 / 3), "Income-focused": (0.5, 0.25, 0.25), "Cautious": (0.25, 0.25, 0.5)}.items():
        r[f"score_{name}"] = wv * r.value_score + wg * r.growth_score + wr * r.risk_score
        r[f"rank_{name}"] = r[f"score_{name}"].rank(ascending=False, method="min").astype(int)
    r["risk_tier"] = pd.qcut(r.risk_score, 3, labels=["Higher risk", "Middle", "Lower risk"])
    res = pd.concat([r, u[~ok]]).assign(ranked=lambda d: d.suburb_id.isin(r.suburb_id))
    res["not_ranked_reason"] = np.select([res.ranked, res.missing_inputs != ""], ["", "missing: " + res.missing_inputs],
                                         "new development: rent history comes from rent areas shared with other suburbs")
    keep = ["suburb_id", "suburb_name", "area_type", "median_cv_2024", "median_rent_weekly", "rent_3bed_house", "lodged_3bed_house_4q",
            "flag_verify_3bed_house", *cols, "rent_change_2y_pa", *[f"s_{c}" for c in cols], "value_score", "growth_score",
            "risk_score", "risk_tier", "score_Balanced", "score_Income-focused", "score_Cautious", "rank_Balanced",
            "rank_Income-focused", "rank_Cautious", "flag_shared_rent_area", "is_new_development", "flag_rapid_growth",
            "ranked", "missing_inputs", "not_ranked_reason"]
    res = res[keep].sort_values(["ranked", "rank_Balanced"], ascending=[False, True])
    assert res.suburb_id.is_unique and res.loc[res.ranked, "score_Balanced"].between(0, 100).all()
    return res


def forecast(prof):
    """File 8 'auckland' model on the suburb's rent now: the same Auckland growth factors and 80% bands (by thin sample)."""
    f = pd.read_csv(CLEAN / "rent_forecast_by_sa2.csv")
    big = f[f.rent_now > 500]  # shortcut: factors read back from File 8's rounded output (error under $0.25); store them in File 8 if exactness matters
    g1, g2 = (big.forecast_rent_y1 / big.rent_now).median(), (big.forecast_rent_y2 / big.rent_now).median()
    band = big.groupby("flag_thin_sample")[["y1_low", "y1_high", "y2_low", "y2_high", "forecast_rent_y1", "forecast_rent_y2"]].apply(lambda d: pd.Series(
        {k: (d[k] / d[f"forecast_rent_y{k[1]}"]).median() for k in ["y1_low", "y1_high", "y2_low", "y2_high"]}))
    o = prof.loc[prof.median_rent_weekly.notna(), ["suburb_id", "suburb_name", "median_rent_weekly", "lodged_bonds_4q",
                                                   "flag_thin_sample", "flag_shared_rent_area", "suburb_source_sa2", "analysis_ready"]]
    o = o.rename(columns={"median_rent_weekly": "rent_now", "lodged_bonds_4q": "lodged_4q"})
    o["forecast_rent_y1"], o["forecast_rent_y2"] = o.rent_now * g1, o.rent_now * g2
    b = band.reindex(o.flag_thin_sample.astype(bool).values).set_index(o.index)
    for k in band.columns:
        o[k] = o[f"forecast_rent_y{k[1]}"] * b[k]
    o["change_y1_pct"], o["change_y2_pct"] = 100 * (g1 - 1), 100 * (g2 - 1)
    o["model"], o["year1_period"], o["year2_period"] = f.model.iloc[0], f.year1_period.iloc[0], f.year2_period.iloc[0]
    assert (o.y1_low <= o.forecast_rent_y1).all() and (o.forecast_rent_y1 <= o.y1_high).all()
    return o[["suburb_id", "suburb_name", "rent_now", "forecast_rent_y1", "y1_low", "y1_high", "change_y1_pct", "forecast_rent_y2",
              "y2_low", "y2_high", "change_y2_pct", "lodged_4q", "flag_thin_sample", "flag_shared_rent_area", "suburb_source_sa2",
              "analysis_ready", "model", "year1_period", "year2_period"]]


def premium(prof, rq, mem):
    """File 6 gap: bond median rent (Oct-Dec 2022, Jan-Mar 2023) / census median rent paid - 1. The suburb census median is
    the weighted mean of SA2 medians (approximate). Landlord-sector shares from summed census counts."""
    h = pd.read_csv(DATA / "census" / "census_2013_2018_2023_households_sa2.csv",
                    usecols=["SA22023_V1_00", "VAR_4_163", "VAR_4_164", "VAR_4_165", "VAR_4_167", "VAR_4_171"]).replace(-999, np.nan)
    h["sa2_code"] = h.SA22023_V1_00.astype(int)
    sec = {"VAR_4_163": "private", "VAR_4_164": "council", "VAR_4_165": "kainga_ora", "VAR_4_167": "community", "VAR_4_171": "stated"}
    c = mem.merge(h[["sa2_code", *sec]].rename(columns=sec), on="sa2_code").groupby("suburb_id")[list(sec.values())].sum(min_count=1)
    w = rq[(rq.dwelling == "ALL") & (rq.beds == "ALL") & rq.quarter.isin(pd.to_datetime(["2022-10-01", "2023-01-01"]))].groupby("suburb_id")
    p = prof.set_index("suburb_id")[["suburb_name", "census_median_rent_weekly_approx", "flag_shared_rent_area",
                                     "suburb_source_sa2", "analysis_ready"]].copy()
    p["bond_rent_census_time"] = w.median_rent.mean()
    p["rent_quarters_census_time"] = w.median_rent.count()
    p["lodged_census_time"] = w.lodged_full.sum()  # full rent-area counts, as File 6
    p["rent_premium_pct"] = 100 * (p.bond_rent_census_time / p.census_median_rent_weekly_approx - 1)
    p["rent_premium_dollars"] = p.bond_rent_census_time - p.census_median_rent_weekly_approx
    p["social_pct"] = 100 * c[["kainga_ora", "council", "community"]].sum(axis=1, min_count=1) / c.stated
    p["kainga_ora_pct"], p["private_landlord_pct"] = 100 * c.kainga_ora / c.stated, 100 * c.private / c.stated
    # same place on both sides: own SA2s only, and a bond figure not shared with another suburb
    p["in_premium_analysis"] = (p.analysis_ready.fillna(False).astype(bool) & p.suburb_source_sa2.isna() & ~p.flag_shared_rent_area
                                & p.rent_premium_pct.notna() & (p.lodged_census_time >= 30))
    assert p.social_pct.dropna().between(0, 100).all()
    return p.reset_index()


if __name__ == "__main__":
    sa2, sub = load_layers()
    units = unit_pieces(sa2, sub)
    lookup, pieces = sa2_to_suburb(sa2, sub, units)
    pop = pd.read_csv(CLEAN / "master_flagged.csv", usecols=["sa2_code", "population_2023"]).fillna({"population_2023": 0})
    subs = suburb_list(sub, lookup, pieces, pop)
    lookup.to_csv(CLEAN / "sa2_to_suburb.csv", index=False, encoding="utf-8")
    subs.to_csv(CLEAN / "suburb_list.csv", index=False, encoding="utf-8")

    mem = members(lookup, subs)
    core = core_figures(mem)
    shares = rent_area_shares(mem)
    rq = suburb_rent_quarterly(load_rent_by_type(), shares)
    rt = rent_by_type(rq)
    allr = rt[(rt.dwelling == "ALL") & (rt.beds == "ALL")].set_index("suburb_id")
    h3 = rt[(rt.dwelling == "House") & (rt.beds == "3")].set_index("suburb_id")
    core["median_rent_weekly"], core["lodged_bonds_4q"], core["rent_areas"] = allr.rent, allr.lodged_bonds_4q, allr.rent_areas
    core["lodged_bonds_4q_in_suburb"], core["active_bonds_in_suburb"] = allr.lodged_bonds_4q_in_suburb, allr.active_bonds_in_suburb
    core["flag_thin_sample"], core["flag_unstable_rent"] = allr.flag_thin_sample, allr.flag_unstable_rent
    core["rent_3bed_house"], core["lodged_3bed_house_4q"] = h3.rent, h3.lodged_bonds_4q
    core["flag_verify_3bed_house"] = h3.flag_thin_sample | h3.flag_unstable_rent
    core["gross_yield_pct"] = 100 * core.median_rent_weekly * 52 / core.median_cv_2024
    core = core.join(rent_trends(rq))
    core = core.join(area_type(mem))
    # a rent area feeding more than one own-SA2 suburb: the suburbs share one rent figure (like flag_borrowed_rent)
    multi = shares[shares.main].groupby("rent_source_sa2").suburb_id.nunique()
    core["flag_shared_rent_area"] = core.index.map(
        shares.assign(m=shares.rent_source_sa2.map(multi) > 1).groupby("suburb_id").m.any()).fillna(False).astype(bool)
    comparable = core.analysis_ready & ~core.flag_crime_hotspot
    lo, hi = core.loc[comparable, "crime_per_1000_residents"].quantile([1 / 3, 2 / 3])
    r = core.crime_per_1000_residents
    core["crime_rating"] = np.select([core.flag_crime_hotspot, r <= lo, r <= hi, r > hi], ["Hotspot", "Low", "Moderate", "High"], "—")
    core.loc[~core.analysis_ready, "crime_rating"] = "—"
    prof = subs[["suburb_id", "suburb_name", "suburb_type", "n_sa2", "sa2_codes", "suburb_source_sa2",
                 "flag_shared_rural_sa2", "caveat"]].merge(core, left_on="suburb_id", right_index=True, how="left")

    # checks: each SA2 counted once (own-SA2 rows) must give the SA2 totals, less the excluded water SA2s
    master = pd.read_csv(CLEAN / "master_flagged.csv")
    kept = master[~master.sa2_code.isin(EXCLUDED)]
    own = prof[prof.suburb_source_sa2.isna()]
    kept = kept.merge(pd.read_csv(CLEAN / "area_profiles_by_sa2.csv")[["sa2_code", "mosques_in_area", "gp_clinics_in_area"]], on="sa2_code")
    for c in ["population_2023", "households_2023", "dwellings_2023", "crime_total", "rating_units", "schools",
              "mosques_in_area", "gp_clinics_in_area"]:
        assert abs(own[c].sum() - kept[c].sum()) < 1e-6, (c, own[c].sum(), kept[c].sum())
    # bonds: each rent area's shares over the own-SA2 suburbs add to 1, so apportioned bonds sum back to MBIE totals
    tot = shares[shares.main].groupby("rent_source_sa2").share.sum()
    assert tot[tot > 0].sub(1).abs().max() < 1e-9, tot[(tot - 1).abs() > 1e-9]
    prof.to_csv(CLEAN / "suburb_profiles.csv", index=False, encoding="utf-8")
    rt.merge(subs[["suburb_id", "suburb_name"]], on="suburb_id").to_csv(CLEAN / "suburb_rent_by_type.csv", index=False, encoding="utf-8")
    screen(prof).round(2).to_csv(CLEAN / "suburb_screen.csv", index=False, encoding="utf-8")
    forecast(prof).round(1).to_csv(CLEAN / "suburb_rent_forecast.csv", index=False, encoding="utf-8")
    premium(prof, rq, mem).round(2).to_csv(CLEAN / "suburb_rent_premium.csv", index=False, encoding="utf-8")
    rq.to_csv(CLEAN / "suburb_rent_quarterly.csv", index=False, encoding="utf-8", date_format="%Y-%m-%d")
    print("ok   suburb_profiles.csv", len(prof), "rows;", int(prof.median_rent_weekly.notna().sum()), "with rent;",
          int(prof.analysis_ready.fillna(False).sum()), "analysis-ready")
    print("ok   sa2_to_suburb.csv", len(lookup), "SA2s ->", lookup.suburb_id.nunique(), "suburbs;",
          dict(lookup.match_basis.value_counts()), int(lookup.unmapped.sum()), "unmapped;",
          int(lookup.straddles_suburbs.sum()), "straddle (<60%)")
    print("ok   suburb_list.csv", len(subs), "rows;", int(subs.suburb_source_sa2.notna().sum()), "share a parent SA2;",
          int(subs.flag_shared_rural_sa2.sum()), "flagged")
