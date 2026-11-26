"""Facility points with File 3's rules (03_area_profiles.ipynb Step 5), for counting inside LINZ suburb boundaries.

Used by build_suburbs.py. File 3 keeps its own copy of these rules for the SA2 files; both drop the GP entries marked
'drop' in data/amenities/gp_clinic_corrections.csv. NZTM (EPSG:2193), so distances are metres.
"""
from pathlib import Path

import geopandas as gpd
import pandas as pd

AM = Path(__file__).parent / "data" / "amenities"
# Year levels each MoE school type serves (File 3); specialist schools, teen parent units and activity centres are left out
YEARS = {"Contributing": (1, 6), "Full Primary": (1, 8), "Intermediate": (7, 8), "Composite": (1, 15),
         "Restricted Composite (Year 7-10)": (7, 10), "Secondary (Year 7-10)": (7, 10), "Secondary (Year 7-15)": (7, 15),
         "Secondary (Year 9-15)": (9, 15), "Secondary (Year 11-15)": (11, 15)}


def _pts(d, lon="lon", lat="lat"):
    return gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d[lon], d[lat]), crs=4326).to_crs(2193)


def gp_clinics():
    """OpenStreetMap GP practices less the reviewed specialist and non-health entries."""
    g = pd.read_csv(AM / "gp_clinics_auckland.csv")
    drop = pd.read_csv(AM / "gp_clinic_corrections.csv").query("decision == 'drop'").osm_id
    return g[~g.osm_id.isin(drop)]


def load_points():
    """{key: (points, label column, count column or None)}; key also names the nearest_* / km_to_nearest_* columns."""
    s = pd.read_csv(AM / "schools_directory.csv", usecols=["Org_Name", "Org_Type", "Authority", "Enrolment_Scheme",
                                                          "Regional_Council", "Status", "Latitude", "Longitude"])
    s = s[(s.Regional_Council == "Auckland Region") & (s.Status == "Open") & s.Org_Type.isin(YEARS)].dropna(subset=["Latitude", "Longitude"])
    yf, yt = s.Org_Type.map(YEARS).str[0], s.Org_Type.map(YEARS).str[1]
    schools = _pts(s, "Longitude", "Latitude")
    reg = pd.read_csv(AM / "mosques_verified.csv")
    mq = pd.concat([reg[reg.status == "verified"], pd.read_csv(AM / "mosques_osm_candidates.csv").query("status == 'keep'")], ignore_index=True)
    mq["name"] = mq.name.fillna("Unnamed Muslim place of worship, " + mq.address)
    halal = _pts(pd.read_csv(AM / "halal_shops_auckland.csv"))
    play = _pts(pd.read_csv(AM / "playgrounds_auckland.csv"))
    play["label"] = play.name.fillna("Playground in " + play.park_name).fillna("(unnamed playground)")
    parks = _pts(pd.read_csv(AM / "parks_auckland.csv"))
    parks["label"] = parks.name.fillna("(unnamed park)")
    return {
        "primary_school": (schools[(yf <= 8).values], "Org_Name", "primary_schools_in_area"),
        "secondary_school": (schools[(yt >= 9).values], "Org_Name", "secondary_schools_in_area"),
        "year1_school": (schools[(yf == 1).values], "Org_Name", "year1_schools_in_area"),
        "mosque": (_pts(mq), "name", "mosques_in_area"),
        "gp_clinic": (_pts(gp_clinics()), "name", "gp_clinics_in_area"),
        "halal_butcher": (halal[halal.kind == "butcher"], "name", "halal_butchers_in_area"),
        "halal_place": (halal, "name", "halal_places_in_area"),
        "playground": (play, "label", "playgrounds_in_area"),
        "park": (parks, "label", "parks_in_area"),
        "supermarket": (_pts(pd.read_csv(AM / "supermarkets_auckland.csv")), "name", "supermarkets_in_area"),
        "shopping_centre": (_pts(pd.read_csv(AM / "shopping_centres_auckland.csv")), "name", "shopping_centres_in_area"),
    }
