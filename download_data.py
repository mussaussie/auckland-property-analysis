"""Download the free raw datasets for the Auckland property dashboard into data/.

Run: python download_data.py   (re-running skips files that already exist)
"""
import csv
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

DATA = Path(__file__).parent / "data"
STATSNZ = "https://services2.arcgis.com/vKb0s8tBIA3bdocZ/arcgis/rest/services"
AKL = "https://services1.arcgis.com/n4yPwebTjJCmXB6W/arcgis/rest/services"
CKAN = "https://catalogue.data.govt.nz/api/3/action/package_show?id="
# shortcut: tenancy.govt.nz file names carry the release month, update these when MBIE republishes
TENANCY = "https://www.tenancy.govt.nz/assets/Uploads/Tenancy/Rental-bond-data/"


def get_json(url, params=None):
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=120)
            r.raise_for_status()
            d = r.json()
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:  # these services drop the odd request; retry before giving up
            if attempt == 3:
                raise
            print("  retry:", e)
            time.sleep(5 * (attempt + 1))


def download(url, path):
    if path.exists():
        return print("skip", path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(path)
    print("ok  ", path.name, f"{path.stat().st_size / 1e6:.1f} MB")


def ckan_url(dataset, name_starts):
    for res in get_json(CKAN + dataset)["result"]["resources"]:
        if res["name"].startswith(name_starts):
            return res["url"]
    raise LookupError(f"{name_starts!r} not in {dataset}")


def arcgis_table(layer, path, centroid=False):
    """Page through an ArcGIS layer's attributes into a CSV; also write its field dictionary."""
    if path.exists():
        return print("skip", path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = get_json(layer, {"f": "json"})["fields"]
    with open(path.with_name(path.stem + "_fields.csv"), "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["name", "alias"]] + [[x["name"], x["alias"]] for x in fields])
    cols = [x["name"] for x in fields] + (["lon", "lat"] if centroid else [])
    tmp, offset = path.with_suffix(".part"), 0
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        while True:
            d = get_json(layer + "/query", {
                "where": "1=1", "outFields": "*", "returnGeometry": "false",
                "returnCentroid": str(centroid).lower(), "outSR": 4326,
                "orderByFields": "OBJECTID", "resultOffset": offset, "f": "json"})
            feats = d["features"]
            for ft in feats:
                row = ft["attributes"]
                if centroid and ft.get("centroid"):
                    row["lon"], row["lat"] = ft["centroid"]["x"], ft["centroid"]["y"]
                w.writerow(row)
            offset += len(feats)
            if offset % 50000 < len(feats):
                print("  ", path.name, offset, flush=True)
            if not feats or not d.get("exceededTransferLimit"):
                break
    tmp.rename(path)
    print("ok  ", path.name, offset, "rows")


def read_layer(name):
    """Read a whole Stats NZ boundary layer, paging past the 2,000 feature limit."""
    # maxAllowableOffset ~10 m keeps the national file small enough for a web map
    q = "/FeatureServer/0/query?where=1%3D1&outFields=*&outSR=4326&maxAllowableOffset=0.0001&f=geojson"
    parts, offset = [], 0
    while True:
        g = gpd.read_file(f"{STATSNZ}/{name}{q}&orderByFields=OBJECTID&resultOffset={offset}")
        parts.append(g)
        offset += len(g)
        if len(g) < 2000:
            return pd.concat(parts)


def boundaries():
    out = DATA / "boundaries" / "auckland_sa2_2023.geojson"
    if out.exists():
        return print("skip", out.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 2018 SA2s are needed to map MBIE rents (published on older SA2 codes) onto 2023 SA2s
    read_layer("Statistical_Area_2_2018").to_file(out.with_name("nz_sa2_2018.geojson"), driver="GeoJSON")
    sa2 = read_layer("Statistical_Area_2_2023")
    sa2.to_file(out.with_name("nz_sa2_2023.geojson"), driver="GeoJSON")
    rc = read_layer("Regional_Council_2023")
    akl = rc[rc.filter(like="NAME").iloc[:, 0].str.contains("Auckland")].geometry.iloc[0]
    sa2 = sa2[sa2.geometry.notna()]
    sa2 = sa2[sa2.representative_point().within(akl)]
    assert 500 < len(sa2) < 700, len(sa2)  # Auckland has roughly 600 SA2s
    sa2.to_file(out, driver="GeoJSON")
    print("ok  ", out.name, len(sa2), "SA2s")


def crime():
    """Police victimisations for the Auckland region by month, crime type and meshblock (Tableau CSV export)."""
    out = DATA / "crime" / "police_victimisations_auckland_meshblock.csv"
    if out.exists():
        return print("skip", out.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    url = "https://public.tableau.com/views/VictimisationsTimeandPlace/Map.csv"
    divisions = ["Assault", "Sexual Offences", "Harm or endanger persons",
                 "Robbery, blackmail, and extortion", "Burglary", "Theft"]
    tmp, total = out.with_suffix(".part"), 0
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year_month", "anzsoc_division", "meshblock", "lat", "lon", "victimisations"])
        # the report holds a rolling 4 years; months outside it come back empty
        for month in pd.date_range("2022-01-01", pd.Timestamp.today(), freq="MS").strftime("%Y-%m-%d"):
            for div in divisions:
                for attempt in range(4):
                    r = requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0"}, params={
                        ":showVizHome": "no", "Region": "Auckland Region", "Year Month": month,
                        # Tableau splits filter values on commas unless they are escaped
                        "ANZSOC Division": div.replace(",", "\\,"),
                        "Select Level of Detail for Map": "4"})  # 4 = meshblock
                    if r.ok:
                        break
                    time.sleep(5 * (attempt + 1))
                r.raise_for_status()
                for row in csv.DictReader(r.content.decode("utf-8-sig").splitlines()):
                    n = int(row["Number of Victimisations"].replace(",", ""))
                    total += n
                    w.writerow([month[:7], div, row["Map Detail Name"], row["Latitude (generated)"],
                                row["Longitude (generated)"], n])
            print("  ", month[:7], total, flush=True)
    assert total > 100000, total  # Auckland records roughly 100k victimisations a year
    tmp.rename(out)
    print("ok  ", out.name, total, "victimisations")


def osm_amenities():
    """Auckland GP practices and halal food places from the Geofabrik NZ OpenStreetMap extract (ODbL)."""
    am = DATA / "amenities"
    gp_out, halal_out = am / "gp_clinics_auckland.csv", am / "halal_shops_auckland.csv"
    if gp_out.exists() and halal_out.exists():
        return print("skip", gp_out.name, halal_out.name)
    import re
    import numpy as np
    import pyogrio  # GDAL's OSM driver reads .pbf directly; no extra package needed
    pbf = am / "osm" / "new-zealand-latest.osm.pbf"
    where = "other_tags LIKE '%doctor%' OR other_tags LIKE '%halal%' OR other_tags LIKE '%clinic%' OR name LIKE '%halal%'"
    parts = []
    for layer, extra in [("points", ""), ("multipolygons", " OR amenity IN ('doctors','clinic')")]:
        g = pyogrio.read_dataframe(pbf, layer=layer, bbox=(174.1, -37.4, 175.6, -36.0), where=where + extra)
        g["osm_id"] = g.filter(regex="^osm_(way_)?id$").bfill(axis=1).iloc[:, 0]
        g["geometry"] = g.to_crs(2193).representative_point().to_crs(4326)  # buildings -> one point
        parts.append(g)
    g = pd.concat(parts, ignore_index=True)
    sa2 = gpd.read_file(DATA / "boundaries" / "auckland_sa2_2023.geojson")[["geometry"]].to_crs(4326)
    g = g[g.index.isin(gpd.sjoin(g, sa2, predicate="within").index)].copy()  # inside an Auckland SA2 (no union: polygons are simplified)
    tag = lambda k: g.other_tags.str.extract(r'"' + re.escape(k) + r'"=>"([^"]*)"')[0]
    for k in ["amenity", "shop", "healthcare", "healthcare:speciality", "diet:halal", "cuisine"]:
        g[k] = g[k].fillna(tag(k)) if k in g else tag(k)
    g["lat"], g["lon"] = g.geometry.y.round(6), g.geometry.x.round(6)
    name = g.name.fillna("")

    # GP: a doctors' surgery (or a clinic named like one), not tagged with a non-general speciality, not a specialist by name
    general = g["healthcare:speciality"].isna() | g["healthcare:speciality"].str.contains("general", na=False)
    gp_name = name.str.contains(r"medical|family (?:practice|doctor|health)|doctors|accident|urgent|health cent", case=False)
    not_gp = name.str.contains(r"specialist|gyn|physio|dermat|radiolog|imaging|orthop|surgical|eye|skin|cosmetic|face doctor|oriental|fertility|dental|lab", case=False)
    is_gp = ((g.amenity.eq("doctors") | g.healthcare.eq("doctor")) | (g.amenity.eq("clinic") & gp_name)) & general & ~not_gp
    gp = g[is_gp].drop_duplicates(["name", "lat", "lon"])

    # Halal: tagged diet:halal yes/only, or 'halal' in the name unless tagged no
    halal = g[g["diet:halal"].isin(["yes", "only"]) | (name.str.contains("halal", case=False) & g["diet:halal"].ne("no"))].copy()
    meat = halal.shop.str.contains("butcher", na=False) | halal.name.str.contains(r"meat|butcher", case=False, na=False)
    halal["kind"] = np.where(meat, "butcher", np.where(halal.shop.notna(), "shop", "eatery"))
    halal = halal.drop_duplicates(["name", "lat", "lon"])

    cols = ["osm_id", "name", "amenity", "shop", "healthcare", "healthcare:speciality", "diet:halal", "cuisine", "lat", "lon"]
    gp[cols].to_csv(gp_out, index=False)
    halal[["kind", *cols]].to_csv(halal_out, index=False)
    print("ok  ", gp_out.name, len(gp), "|", halal_out.name, len(halal), dict(halal.kind.value_counts()))


def osm_parks():
    """Auckland public playgrounds and parks from the same OpenStreetMap extract (ODbL). Slow: ~3 min to scan the pbf."""
    am = DATA / "amenities"
    pg_out, park_out = am / "playgrounds_auckland.csv", am / "parks_auckland.csv"
    if pg_out.exists() and park_out.exists():
        return print("skip", pg_out.name, park_out.name)
    import pyogrio
    pbf, bbox = am / "osm" / "new-zealand-latest.osm.pbf", (174.1, -37.4, 175.6, -36.0)
    pts = pyogrio.read_dataframe(pbf, layer="points", bbox=bbox, where="other_tags LIKE '%\"leisure\"=>\"playground\"%' OR other_tags LIKE '%\"leisure\"=>\"park\"%'")
    pts["leisure"] = pts.other_tags.str.extract(r'"leisure"=>"([^"]*)"')[0]
    polys = pyogrio.read_dataframe(pbf, layer="multipolygons", bbox=bbox, where="leisure IN ('playground','park')")
    polys["osm_id"] = polys.filter(regex="^osm_(way_)?id$").bfill(axis=1).iloc[:, 0]
    g = pd.concat([pts, polys], ignore_index=True)[["osm_id", "name", "leisure", "other_tags", "geometry"]].to_crs(2193)
    access = g.other_tags.str.extract(r'"access"=>"([^"]*)"')[0]
    private = access.isin(["private", "no", "customers"])  # school, childcare and fast-food playgrounds; private parks
    print(f"     dropped {private.sum()} private / customer-only features")
    g = g[~private].copy()
    g["area_ha"] = (g.area / 1e4).round(2)
    parks = g[g.leisure == "park"]
    play = g[g.leisure == "playground"].copy()
    # Most playgrounds have no name: label them by the park they sit in
    inside = gpd.sjoin(gpd.GeoDataFrame(play[[]], geometry=play.representative_point()), parks[["name", "area_ha", "geometry"]], predicate="within")
    play["park_name"] = inside.sort_values("area_ha").groupby(level=0)["name"].first()  # smallest enclosing park
    sa2 = gpd.read_file(DATA / "boundaries" / "auckland_sa2_2023.geojson")[["geometry"]].to_crs(2193)
    out = []
    for d in (play, parks):
        d = d.assign(geometry=d.representative_point())
        d = d[d.index.isin(gpd.sjoin(d, sa2, predicate="within").index)].to_crs(4326)
        d["lat"], d["lon"] = d.geometry.y.round(6), d.geometry.x.round(6)
        out.append(d.drop_duplicates(["lat", "lon"]))
    play, parks = out
    play[["osm_id", "name", "park_name", "area_ha", "lat", "lon"]].to_csv(pg_out, index=False)
    parks[["osm_id", "name", "area_ha", "lat", "lon"]].to_csv(park_out, index=False)
    print("ok  ", pg_out.name, len(play), f"({play.park_name.notna().sum()} inside a mapped park) |", park_out.name, len(parks))


if __name__ == "__main__":
    crime()
    download(TENANCY + "detailed-quarterly-tenancy-q1-2020q3-november-2026.csv", DATA / "rental" / "mbie_quarterly_sa2_2020_2026.csv")
    download(TENANCY + "detailed-quarterly-tenancy-93-to-19.zip", DATA / "rental" / "mbie_quarterly_sa2_1993_2019.zip")
    download(TENANCY + "detailed-monthly-tla-tenancy-november-2026.csv", DATA / "rental" / "mbie_monthly_ta.csv")

    download("https://gtfs.at.govt.nz/gtfs.zip", DATA / "amenities" / "at_gtfs.zip")
    download(ckan_url("c1923d33-e781-46c9-9ea1-d9b850082be4", "Schools Directory"), DATA / "amenities" / "schools_directory.csv")

    download(ckan_url("urban-development", "NPS UD data catalogue"), DATA / "property_prices" / "hud_ta_sales_rents.zip")

    boundaries()

    # OpenStreetMap NZ extract (~400 MB, ODbL); osm_amenities() keeps Auckland GP practices and halal food places
    download("https://download.geofabrik.de/australia-oceania/new-zealand-latest.osm.pbf", DATA / "amenities" / "osm" / "new-zealand-latest.osm.pbf")
    osm_amenities()
    osm_parks()

    census = STATSNZ + "/2023_Census_totals_by_topic_for_{}_by_SA2/FeatureServer/{}"
    # layer 3 = individuals part 2; its coast-clipped twin (layer 2) is published empty
    for topic, layer in [("individuals", 0), ("individuals", 3), ("households", 0), ("dwellings", 0)]:
        suffix = "_part2" if layer == 3 else ""
        arcgis_table(census.format(topic, layer), DATA / "census" / f"census_2013_2018_2023_{topic}{suffix}_sa2.csv")

    # slowest step: ~624k rating units at 2,000 per request
    arcgis_table(AKL + "/AGOL_RateAccountInfo1_gdb/FeatureServer/0", DATA / "property_prices" / "auckland_cv_2021_2024.csv", centroid=True)
