"""Regenerate the evidence in data/boundaries/sa2_to_suburb_review.csv (the 50 reviewed SA2s) and report any difference.

Evidence per SA2: rating units by LINZ suburb, 2023 census residents (SA1 counts, each SA1 split by where its rating units
sit, by land area where it has none), and council address suburb labels (middle line of FORMATTEDADDRESS).
Run after build_suburbs.py:  python review_evidence.py   (exit code 1 if anything differs beyond rounding)
"""
import sys
import unicodedata

import geopandas as gpd
import pandas as pd

from build_suburbs import DATA, load_layers, sa2_to_suburb, unit_pieces

TOL = {"candidates_pct_units": 0.15, "residents_by_suburb": 0.15, "council_address_suburbs": 1}  # rounding in the stored text


def parse(s):
    return {} if pd.isna(s) or s == "" else {k.strip(): float(v) for k, v in (p.rsplit(" ", 1) for p in str(s).split("; "))}


def fmt(d, n, digits=1):
    top = sorted(((k, round(v, digits)) for k, v in d.items()), key=lambda kv: -kv[1])[:n]
    return "; ".join(f"{k} {round(v, digits) if digits else int(round(v))}" for k, v in top)


def evidence(codes):
    sa2, sub = load_layers()
    sa2 = sa2[sa2.sa2_code.isin(codes)]
    cv = pd.read_csv(DATA / "property_prices" / "auckland_cv_2021_2024.csv", usecols=["FORMATTEDADDRESS", "lon", "lat"]).dropna(subset=["lon"])
    cv = gpd.GeoDataFrame(cv, geometry=gpd.points_from_xy(cv.lon, cv.lat), crs=4326).to_crs(2193)
    cv = gpd.sjoin(cv, sa2[["sa2_code", "geometry"]], predicate="within").drop(columns="index_right")
    cv = gpd.sjoin(cv, sub[["suburb_name", "geometry"]], predicate="within", how="left").drop(columns="index_right")
    parts = cv.FORMATTEDADDRESS.fillna("").str.split("\r")  # street / locality / "Auckland 2110"; council mixes "Drury" and "DRURY"
    cv["label"] = parts.map(lambda p: unicodedata.normalize("NFKD", p[-2]).encode("ascii", "ignore").decode().title() if len(p) >= 3 else "?")

    sa1 = gpd.read_file(DATA / "census" / "sa1_2023_population_auckland.geojson").to_crs(2193)
    sa1 = sa1.rename(columns={"SA12023_V1_00": "sa1", "VAR_1_3": "residents"})
    sa1["residents"] = pd.to_numeric(sa1.residents, errors="coerce").fillna(0)
    sa1["geometry"] = sa1.make_valid()
    rep = gpd.GeoDataFrame(sa1[["sa1"]], geometry=sa1.representative_point(), crs=sa1.crs)
    sa1 = sa1.merge(gpd.sjoin(rep, sa2[["sa2_code", "geometry"]], predicate="within")[["sa1", "sa2_code"]], on="sa1")
    cv = gpd.sjoin(cv, sa1[["sa1", "geometry"]], predicate="within", how="left").drop(columns="index_right")
    area = gpd.overlay(sa1.assign(a=sa1.area), sub[["suburb_name", "geometry"]], how="intersection", keep_geom_type=True)
    area["share"] = area.area / area.a

    rows = []
    for code, g in sa1.groupby("sa2_code"):
        u = cv[cv.sa2_code == code]
        res, split = {}, 0
        for _, s in g.iterrows():
            k = u[u.sa1 == s.sa1].suburb_name.value_counts(normalize=True)
            if k.empty:
                k = area[area.sa1 == s.sa1].set_index("suburb_name").share
            split += int(k.between(0.05, 0.95).any())  # residents depend on the split: 5-95% of the SA1 on one side
            for name, w in k.items():
                res[name] = res.get(name, 0) + s.residents * w
        tot = sum(res.values())
        rows.append({"sa2_code": code, "residents_sa1": int(g.residents.sum()), "sa1s": len(g), "sa1s_split": split,
                     "candidates_pct_units": fmt((100 * u.suburb_name.value_counts(normalize=True)).to_dict(), None),
                     "residents_by_suburb": fmt({k: 100 * v / tot for k, v in res.items() if v > 0}, 4) if tot else "",
                     "council_address_suburbs": fmt((100 * u.label.value_counts(normalize=True)).to_dict(), 4, 0)})
    return pd.DataFrame(rows)


def compare(rv, ev):
    m = rv.merge(ev, on="sa2_code", suffixes=("", "_new"))
    out = []
    for _, r in m.iterrows():
        for c in ["residents_sa1", "sa1s", "sa1s_split"]:
            if int(r[c]) != int(r[c + "_new"]):
                out.append((r.sa2_name, c, r[c], r[c + "_new"]))
        for c, tol in TOL.items():
            a, b = parse(r[c]), parse(r[c + "_new"])
            # every name in the stored (top-n) list must reappear within rounding; 'nan' is stored where 0 SA1 residents
            # gave 0/0 (Inlet Waitematā Harbour), which the regenerated text leaves blank
            if any(a[k] == a[k] and (b.get(k) is None or abs(a[k] - b[k]) > tol) for k in a):
                out.append((r.sa2_name, c, r[c], r[c + "_new"]))
    return pd.DataFrame(out, columns=["sa2_name", "field", "committed", "regenerated"])


if __name__ == "__main__":
    rv = pd.read_csv(DATA / "boundaries" / "sa2_to_suburb_review.csv", encoding="utf-8-sig")
    assert len(rv) == 50 and rv.sa2_code.is_unique
    d = compare(rv, evidence(rv.sa2_code))
    sa2, sub = load_layers()
    sa2_to_suburb(sa2, sub, unit_pieces(sa2, sub))  # asserts the build still reproduces every reviewed decision
    out = DATA / "boundaries" / "sa2_to_suburb_review_check.csv"
    d.to_csv(out, index=False, encoding="utf-8")
    print(f"{len(rv)} reviewed SA2s; {d.sa2_name.nunique()} with differences ({len(d)} fields) -> {out.name}")
    print(d.to_string(index=False) if len(d) else "all evidence reproduced within rounding")
    sys.exit(1 if len(d) else 0)
