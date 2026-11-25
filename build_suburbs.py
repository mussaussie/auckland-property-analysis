"""Map each SA2 to a LINZ suburb (step 1 of suburb results). Later steps aggregate SA2 measures per suburb.

Run after download_data.py and build_master.py:  python build_suburbs.py
"""
from pathlib import Path

import geopandas as gpd
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


if __name__ == "__main__":
    sa2, sub = load_layers()
    units = unit_pieces(sa2, sub)
    lookup, pieces = sa2_to_suburb(sa2, sub, units)
    pop = pd.read_csv(CLEAN / "master_flagged.csv", usecols=["sa2_code", "population_2023"]).fillna({"population_2023": 0})
    subs = suburb_list(sub, lookup, pieces, pop)
    lookup.to_csv(CLEAN / "sa2_to_suburb.csv", index=False, encoding="utf-8")
    subs.to_csv(CLEAN / "suburb_list.csv", index=False, encoding="utf-8")
    print("ok   sa2_to_suburb.csv", len(lookup), "SA2s ->", lookup.suburb_id.nunique(), "suburbs;",
          dict(lookup.match_basis.value_counts()), int(lookup.unmapped.sum()), "unmapped;",
          int(lookup.straddles_suburbs.sum()), "straddle (<60%)")
    print("ok   suburb_list.csv", len(subs), "rows;", int(subs.suburb_source_sa2.notna().sum()), "share a parent SA2;",
          int(subs.flag_shared_rural_sa2.sum()), "flagged")
