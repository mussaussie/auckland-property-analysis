"""Build the cleaned Auckland dataset: one row per SA2 (2023 boundaries) plus a rent time series.

Run after download_data.py:  python build_master.py
"""
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

DATA = Path(__file__).parent / "data"
CLEAN = DATA / "clean"

# Stats NZ column code -> our name (see data/census/*_fields.csv for the full dictionary)
CENSUS = {
    "individuals": {"VAR_1_3": "population_2023", "VAR_1_69": "median_age", "VAR_1_96": "_overseas",
                    "VAR_1_99": "_birth_stated", "VAR_1_158": "_european", "VAR_1_159": "_maori",
                    "VAR_1_160": "_pacific", "VAR_1_161": "_asian", "VAR_1_168": "_eth_stated",
                    "VAR_1_2": "population_2018", "VAR_1_80": "_under_15", "VAR_1_83": "_65_plus", "VAR_1_84": "_age_total",
                    "VAR_1_403": "_no_religion", "VAR_1_404": "_buddhist", "VAR_1_405": "_christian",
                    "VAR_1_406": "_hindu", "VAR_1_407": "_muslim", "VAR_1_415": "_religion_stated"},
    "individuals_part2": {"VAR_2_404": "median_personal_income",
                          "VAR_2_245": "_bachelor", "VAR_2_246": "_postgrad", "VAR_2_247": "_masters",
                          "VAR_2_248": "_doctorate", "VAR_2_252": "_qual_stated"},
    "households": {"VAR_4_3": "households_2023", "VAR_4_225": "median_household_income",
                   "VAR_4_184": "_owned", "VAR_4_186": "_trust", "VAR_4_189": "_tenure_stated",
                   "VAR_4_261": "census_median_rent_weekly",
                   "VAR_4_48": "_crowded", "VAR_4_57": "_crowding_stated",
                   "VAR_4_74": "_one_family", "VAR_4_75": "_two_family", "VAR_4_76": "_three_family",
                   "VAR_4_78": "_one_person", "VAR_4_81": "_composition_stated",
                   "VAR_4_136": "_no_vehicle", "VAR_4_144": "_vehicle_stated"},
    "dwellings": {"VAR_3_59": "dwellings_2023", "VAR_3_80": "_private_dwellings", "VAR_3_82": "_separate_house",
                  "VAR_3_173": "avg_bedrooms", "VAR_3_29": "_always_damp", "VAR_3_30": "_sometimes_damp",
                  "VAR_3_34": "_damp_stated"},
}


def points(df, lon, lat):
    df = df.dropna(subset=[lon, lat])
    return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df[lon], df[lat]), crs=4326)


def by_sa2(pts, sa2):
    """Attach the SA2 each point falls in; points outside Auckland are dropped."""
    return gpd.sjoin(pts, sa2[["sa2_code", "geometry"]], predicate="within").drop(columns="index_right")


def load_rent():
    cols = ["TimeFrame", "Location Id", "Dwelling Type", "Number Of Beds", "Median Rent", "Active Bonds", "Total Bonds"]
    old = pd.read_csv(DATA / "rental" / "mbie_quarterly_sa2_1993_2019.zip", usecols=cols, dtype=str)
    new = pd.read_csv(DATA / "rental" / "mbie_quarterly_sa2_2020_2026.csv", usecols=cols, dtype=str)
    r = pd.concat([old, new])
    r = r[(r["Dwelling Type"] == "ALL") & (r["Number Of Beds"] == "ALL")]
    r = r[pd.to_numeric(r["Location Id"], errors="coerce") > 0]  # drops the national (-99) and unknown rows
    return pd.DataFrame({
        "sa2_2018": r["Location Id"].astype(float).astype(int).astype(str),
        "quarter": pd.to_datetime(r["TimeFrame"], dayfirst=True),
        "median_rent": pd.to_numeric(r["Median Rent"], errors="coerce"),
        "active_bonds": pd.to_numeric(r["Active Bonds"], errors="coerce"),
        "lodged_bonds": pd.to_numeric(r["Total Bonds"], errors="coerce"),  # new bonds lodged in the quarter
    }).dropna(subset=["median_rent"])


def census_counts():
    """Census columns by SA2 code (str); negative values are Stats NZ suppression codes, not counts."""
    out = []
    for table, names in CENSUS.items():
        c = pd.read_csv(DATA / "census" / f"census_2013_2018_2023_{table}_sa2.csv",
                        usecols=["SA22023_V1_00", *names], dtype={"SA22023_V1_00": str})
        c = c.dropna(subset=["SA22023_V1_00"]).set_index("SA22023_V1_00").rename(columns=names)
        out.append(c.where(c >= 0))
    return pd.concat(out, axis=1)


def census_shares(m):
    """Turn the _counts into pct_ shares (also used on summed counts for suburbs) and drop the counts."""
    m["pct_overseas_born"] = 100 * m["_overseas"] / m["_birth_stated"]
    for g in ["european", "maori", "pacific", "asian"]:  # people can report several, so these overlap
        m[f"pct_{g}"] = 100 * m[f"_{g}"] / m["_eth_stated"]
    m["pct_owner_occupied"] = 100 * (m["_owned"] + m["_trust"]) / m["_tenure_stated"]
    m["pop_change_2018_2023_pct"] = 100 * (m["population_2023"] / m["population_2018"].where(m["population_2018"] > 0) - 1)
    m["pct_under_15"] = 100 * m["_under_15"] / m["_age_total"]
    m["pct_65_plus"] = 100 * m["_65_plus"] / m["_age_total"]
    for g in ["no_religion", "christian", "muslim", "hindu", "buddhist"]:  # people can report several religions too
        m[f"pct_{g}"] = 100 * m[f"_{g}"] / m["_religion_stated"]
    m["pct_bachelor_plus"] = 100 * m[["_bachelor", "_postgrad", "_masters", "_doctorate"]].sum(axis=1, min_count=1) / m["_qual_stated"]
    m["pct_crowded"] = 100 * m["_crowded"] / m["_crowding_stated"]
    m["pct_family_households"] = 100 * (m["_one_family"] + m["_two_family"] + m["_three_family"]) / m["_composition_stated"]
    m["pct_one_person"] = 100 * m["_one_person"] / m["_composition_stated"]
    m["pct_no_vehicle"] = 100 * m["_no_vehicle"] / m["_vehicle_stated"]
    m["pct_separate_house"] = 100 * m["_separate_house"] / m["_private_dwellings"]
    m["pct_damp"] = 100 * (m["_always_damp"] + m["_sometimes_damp"]) / m["_damp_stated"]
    return m.drop(columns=[c for c in m if c.startswith("_")])


def main():
    CLEAN.mkdir(exist_ok=True)
    sa2 = gpd.read_file(DATA / "boundaries" / "auckland_sa2_2023.geojson").rename(
        columns={"SA22023_V1_00": "sa2_code", "SA22023_V1_00_NAME": "sa2_name", "LAND_AREA_SQ_KM": "land_area_sq_km"})
    sa2["sa2_code"] = sa2["sa2_code"].astype(str)
    centre = sa2.representative_point()
    m = sa2[["sa2_code", "sa2_name", "land_area_sq_km"]].assign(lat=centre.y, lon=centre.x).set_index("sa2_code")

    m = census_shares(m.join(census_counts()))

    # --- capital values: every rating unit, as the source has no residential/commercial flag
    cv = pd.read_csv(DATA / "property_prices" / "auckland_cv_2021_2024.csv",
                     usecols=["CV", "LV", "LCV", "LLV", "lon", "lat"])
    g = by_sa2(points(cv, "lon", "lat"), sa2).groupby("sa2_code")
    m = m.join(pd.DataFrame({
        "rating_units": g.size(), "median_cv_2021": g["CV"].median(), "median_cv_2024": g["LCV"].median(),
        "median_land_value_2024": g["LLV"].median()}))
    m["cv_change_2021_2024_pct"] = 100 * (m["median_cv_2024"] / m["median_cv_2021"] - 1)
    m["land_share_of_cv_pct"] = 100 * m["median_land_value_2024"] / m["median_cv_2024"]

    # --- rent: MBIE publishes on 2018 SA2 codes, so each 2023 SA2 takes the 2018 SA2 its centre sits in
    old = gpd.read_file(DATA / "boundaries" / "nz_sa2_2018.geojson")[["SA22018_V1_00", "geometry"]]
    link = gpd.sjoin(gpd.GeoDataFrame(sa2[["sa2_code"]], geometry=centre, crs=4326), old, predicate="within")
    link = link[["sa2_code"]].assign(sa2_2018=link["SA22018_V1_00"].astype(str))
    # rent_source_sa2 = the MBIE (2018) SA2 the rent comes from: SA2s sharing it share one rent figure and bond count
    m["rent_source_sa2"] = link.set_index("sa2_code")["sa2_2018"]
    rent = (load_rent().merge(link, on="sa2_2018").rename(columns={"sa2_2018": "rent_source_sa2"})
            .sort_values(["sa2_code", "quarter"]))
    rent.to_csv(CLEAN / "rent_timeseries_by_sa2.csv", index=False, date_format="%Y-%m-%d")
    latest = rent["quarter"].max()
    year = rent[rent["quarter"] > latest - pd.DateOffset(years=1)].groupby("sa2_code")  # last 4 quarters
    then = rent[(rent["quarter"] > latest - pd.DateOffset(years=6))
                & (rent["quarter"] <= latest - pd.DateOffset(years=5))].groupby("sa2_code")["median_rent"].mean()
    m["median_rent_weekly"] = year["median_rent"].mean()
    m["active_bonds"] = year["active_bonds"].last()
    m["rent_change_5y_pct"] = 100 * (m["median_rent_weekly"] / then - 1)
    m["gross_yield_pct"] = 100 * m["median_rent_weekly"] * 52 / m["median_cv_2024"]

    # --- crime: latest 12 months, by type
    crime = pd.read_csv(DATA / "crime" / "police_victimisations_auckland_meshblock.csv")
    months = sorted(crime.loc[crime["victimisations"] > 0, "year_month"].unique())[-12:]
    crime = crime[crime["year_month"].isin(months)]
    placed = by_sa2(points(crime, "lon", "lat"), sa2)
    assert placed["victimisations"].sum() > 0.95 * crime["victimisations"].sum(), "crime points fell outside SA2s"
    t = placed.pivot_table(index="sa2_code", columns="anzsoc_division", values="victimisations", aggfunc="sum")
    t.columns = ["crime_" + c.split(",")[0].lower().replace(" ", "_") for c in t.columns]
    m = m.join(t)
    m[list(t.columns)] = m[list(t.columns)].fillna(0)
    m["crime_total"] = m[list(t.columns)].sum(axis=1)
    # shortcut: resident-based rate, so the CBD and shopping centres look worse than they are for residents
    # left blank under 100 residents (harbours, industrial areas), where a rate is meaningless
    m["crime_per_1000_residents"] = 1000 * m["crime_total"] / m["population_2023"].where(m["population_2023"] >= 100)

    # --- amenities
    schools = pd.read_csv(DATA / "amenities" / "schools_directory.csv", usecols=["Latitude", "Longitude"])
    with zipfile.ZipFile(DATA / "amenities" / "at_gtfs.zip").open("stops.txt") as f:
        stops = pd.read_csv(f, usecols=["stop_lat", "stop_lon", "location_type"])
    stops = stops[stops["location_type"] != 1]  # 1 = parent station, which would double count its platforms
    m["schools"] = by_sa2(points(schools, "Longitude", "Latitude"), sa2).groupby("sa2_code").size()
    m["pt_stops"] = by_sa2(points(stops, "stop_lon", "stop_lat"), sa2).groupby("sa2_code").size()
    m[["schools", "pt_stops"]] = m[["schools", "pt_stops"]].fillna(0).astype(int)

    assert len(m) == len(sa2) and m.index.is_unique
    assert m["median_cv_2024"].notna().sum() > 500 and m["median_rent_weekly"].notna().sum() > 400
    m.round(2).to_csv(CLEAN / "master_dataset_by_sa2.csv")
    print(m.notna().sum().to_string())
    print(m.describe().T[["min", "50%", "max"]].round(1).to_string())
    print("crime months:", months[0], "to", months[-1], "| latest rent quarter:", latest.date())


if __name__ == "__main__":
    main()
