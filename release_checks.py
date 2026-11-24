"""Release checks: the figures and decisions the dashboard presents, not just that pages load.

Run before every release:  python release_checks.py
Exit code 0 = all checks passed. Expected values come from METRIC_RULES.md (canonical) and File 8's backtest.
"""
import gc
import html
import io
import re
import subprocess
import sys
import warnings

import pandas as pd
from docx import Document
from pypdf import PdfReader
from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
from streamlit.testing.v1 import AppTest

warnings.filterwarnings("ignore")
CLEAN = "data/clean"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))


def run(view, suburb=None, setup=None, mosques=False):
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["show_mosques"] = mosques  # the sidebar toggle; off by default for visitors
    if suburb:
        at.session_state["suburb"] = suburb
    at.session_state["view"] = view
    at.run()
    if setup:
        setup(at)
        at.run()
    return at


def text(at):
    return html.unescape("\n".join(str(e.value) for e in list(at.markdown) + list(at.caption) + list(at.info) + list(at.warning)))


def kpi(at, label):
    m = re.search(rf'<div class="l">{re.escape(label)}</div><div class="v">([^<]*)</div><div class="c">([^<]*)</div>', text(at))
    return (m.group(1), m.group(2)) if m else (None, None)


def widget(items, label):
    return next(w for w in items if w.label == label)


# ---------- data ----------
sa2 = pd.read_csv(f"{CLEAN}/master_flagged.csv")
rent_m = pd.read_csv(f"{CLEAN}/auckland_rent_monthly.csv")
bt = pd.read_csv(f"{CLEAN}/rent_forecast_backtest.csv").set_index(["test", "h", "model"])["mape"]

check("Headline: Auckland median rent $643/wk (mean of last 3 monthly medians)", round(rent_m["median_rent"].tail(3).mean()) == 643,
      f"{rent_m['median_rent'].tail(3).mean():.1f}")
check("Headline: 633 SA2s, 599 analysis-ready, population 1,656,417",
      (len(sa2), int(sa2["analysis_ready"].sum()), int(sa2["population_2023"].sum())) == (633, 599, 1656417))
check("Shared rent sources: 142 SA2s share a figure; 527 distinct rent areas with rent",
      (int(sa2["flag_borrowed_rent"].sum()), sa2.loc[sa2["median_rent_weekly"].notna(), "rent_source_sa2"].nunique()) == (142, 527))
expected = {("trained to Sep 2024", 1): (5.0, 4.7), ("trained to Sep 2024", 2): (6.2, 5.5),
            ("13 origins 2012-2024", 1): (5.1, 5.8), ("13 origins 2012-2024", 2): (6.9, 8.5)}
check("Forecast benchmark: scenario vs unchanged-rent errors match File 8",
      all((bt[t, h, "auckland"], bt[t, h, "naive"]) == v for (t, h), v in expected.items()))
refreshed = subprocess.run(["git", "log", "-1", "--format=%cs", "--", CLEAN], capture_output=True, text=True).stdout.strip()
app_src = open("app.py", encoding="utf-8").read()
check("Data & Methods refresh date matches the last data/clean commit",
      refreshed and pd.Timestamp(refreshed).strftime("%-d %B %Y" if sys.platform != "win32" else "%#d %B %Y") in app_src, refreshed)
check("No 'reliable rent' wording left in app.py", not re.search(r"reliable (rent|figure|typical)|Reliable (rent|figure)", app_src))

# ---------- app ----------
VIEWS = ["Overview", "Rent in Auckland", "Explore suburb", "Compare suburbs", "Opportunity finder", "Map lab", "Suburb in plain English",
         "Find a rental under my budget", "Family screen", "Data & Methods", "Glossary"]
for v in VIEWS:
    at = run(v)
    check(f"Page renders without exceptions: {v}", not at.exception, "; ".join(str(e.value) for e in at.exception)[:200])
    if v == "Overview":
        check("Overview shows the $643/wk headline", "$643/wk" in text(at))

# Reference family search (METRIC_RULES): 3-bed house <= $580 -> 4 under budget on 2 rent areas, none passing, 138 no estimate
at = run("Family screen")
under, under_cap = kpi(at, "Under budget")
check("Reference family search: 4 under budget on 2 rent areas, 0 pass sample checks, 138 no rent figure",
      (under, kpi(at, "Passes sample checks")[0], kpi(at, "No rent figure")[0]) == ("4", "0", "138") and "2 distinct MBIE rent areas" in under_cap,
      f"{under} / {kpi(at, 'Passes sample checks')[0]} / {kpi(at, 'No rent figure')[0]} / {under_cap}")
house_n = kpi(at, "Areas pass other filters")[0]
apt = run("Family screen", setup=lambda a: widget(a.selectbox, "Dwelling").set_value("Apartment"))
ready = sa2[sa2["analysis_ready"] & ~sa2["flag_crime_hotspot"]]
areas = pd.read_csv(f"{CLEAN}/area_profiles_by_sa2.csv")[["sa2_code", "area_type"]]
ready = ready.drop(columns=[c for c in ["area_type"] if c in ready]).merge(areas, on="sa2_code")
check("Apartment inclusion: house search leaves out apartment & inner-city areas; apartment search includes them",
      int(house_n) == (ready["area_type"] != "Apartments & inner city").sum() and int(kpi(apt, "Areas pass other filters")[0]) == len(ready),
      f"house {house_n}, apartment {kpi(apt, 'Areas pass other filters')[0]}, ready non-hotspot {len(ready)}")

# Zero-match budget search with broader-rent fallbacks kept apart (review case: $600, 3-bed house -> 0 matches, 13 to investigate)
at = run("Find a rental under my budget")
t = text(at)
fb = [d.value for d in at.dataframe if "Rent covers" in d.value.columns]
check("Zero-match search: $600 3-bed house has no budget matches and says so",
      "No area has a typical rent that passes the sample checks" in t and "areas where a typical" not in t)
check("Fallbacks shown separately: 'Areas to investigate using broader rent data (13)'",
      "Areas to investigate using broader rent data (13)" in t and len(fb) == 1 and len(fb[0]) == 13, f"rows {len(fb[0]) if fb else 0}")
check("Each fallback row names its coverage and carries bedrooms and budget into the listing link",
      bool(fb) and fb[0]["Rent covers"].str.contains("all bedroom counts").all()
      and fb[0]["Live listings"].str.contains("bedrooms_min=3&bedrooms_max=3").all() and fb[0]["Live listings"].str.contains("price_max=600").all())
at = run("Find a rental under my budget", setup=lambda a: widget(a.number_input, "My budget ($ a week)").set_value(200))
check("Zero-match search at $200: no matches, no fallbacks", "No area has a typical rent" in text(at) and "Areas to investigate" not in text(at))
at = run("Find a rental under my budget", setup=lambda a: widget(a.number_input, "My budget ($ a week)").set_value(700))
ok = [d.value for d in at.dataframe if "Quarters with data (of 4)" in d.value.columns]
check("Budget matches show lodgements, quarters and data period ($700, 3-bed house)",
      bool(ok) and len(ok[0]) > 0 and (ok[0]["New rentals (12 months)"] >= 30).all() and "average of Oct 2025–Sep 2026" in text(at),
      f"rows {len(ok[0]) if ok else 0}")

# The shared search (search.py) the AI chat will call gives the same answers as the pages
import search  # noqa: E402

data = search.load_data()
x, y = search.rental_search(data, 580, "House", "3"), search.rental_search(data, 600, "House", "3")
check("Shared search (for AI chat): reference $580 and zero-match $600 3-bed house results",
      (len(x["under"]), len(x["matches"]), (x["areas"]["check"] == "no estimate").sum(), x["cheapest_ok"]) == (4, 0, 138, 607.5)
      and len(y["matches"]) == 0 and len(y["fallbacks"]) == 13)

# Mosque columns in both search tables come from the same area record as the profile (example: Avondale Central)
prof = pd.read_csv(f"{CLEAN}/area_profiles_by_sa2.csv").set_index("sa2_name")
NOTE = "Distance is straight-line from the area's representative point. The mapped mosque list may be incomplete."


def wide_open(a, budget_label, dwelling_label):
    widget(a.number_input, budget_label).set_value(2000)
    widget(a.selectbox, dwelling_label).set_value("ALL")
    widget(a.selectbox, "Bedrooms").set_value("ALL")


for view, budget_label, dwelling_label in [("Family screen", "Budget ($/wk)", "Dwelling"),
                                           ("Find a rental under my budget", "My budget ($ a week)", "Home type")]:
    at = run(view, setup=lambda a: wide_open(a, budget_label, dwelling_label), mosques=True)
    tab = [d.value for d in at.dataframe if "Nearest mapped mosque" in d.value.columns][0]
    km = "Km to mosque (mapped)" if view == "Family screen" else "Mosque (km)"
    p = prof.loc[tab["Area"]]
    zero = p["mosques_in_area"].eq(0).values
    check(f"{view}: every row's mosque name, km and inside-count match the area profile ({len(tab)} rows)",
          (tab["Nearest mapped mosque"].values == p["nearest_mosque"].values).all() and (tab[km].values == p["km_to_nearest_mosque"].values).all()
          and (tab["Mosque inside area"].values[zero] == "No mosque mapped inside this SA2").all() and NOTE in text(at))
    av = tab[tab["Area"].str.startswith("Avondale Central")]
    check(f"{view}: Avondale Central shows Avondale Islamic Centre (NZMA), 0.4 km",
          len(av) == 1 and av["Nearest mapped mosque"].iloc[0] == "Avondale Islamic Centre (NZMA)" and av[km].iloc[0] == 0.4)
av_name = next(n for n in prof.index if n.startswith("Avondale Central"))
at = run("Suburb in plain English", suburb=av_name, mosques=True)
check("Suburb in plain English: Avondale Central profile shows the same mosque and distance",
      "Nearest mapped mosque: Avondale Islamic Centre (NZMA), 0.4 km" in text(at))
zero_area = prof[prof["mosques_in_area"].eq(0) & prof.index.isin(sa2.loc[sa2["analysis_ready"], "sa2_name"])].index[0]
at = run("Suburb in plain English", suburb=zero_area, mosques=True)
check(f"Zero inside-count wording with nearest still named ({zero_area})",
      f"No mosque mapped inside this SA2. Nearest mapped mosque: {prof.loc[zero_area, 'nearest_mosque']}" in text(at))

# Mosque information is the visitor's choice: hidden by default everywhere, shown when the sidebar toggle is on
def reports(at):
    """Text of the Word and PDF reports the page offers for download."""
    stores = [o for o in gc.get_objects() if isinstance(o, MemoryMediaFileStorage)]  # one per AppTest run
    out = {}
    for b in at.get("download_button"):
        fid = b.proto.url.split("/")[-1].split(".")[0]
        data = next(s._files_by_id[fid].content for s in stores if fid in s._files_by_id)
        out[b.proto.label] = ("\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs) if "Word" in b.proto.label
                              else "\n".join(pg.extract_text() for pg in PdfReader(io.BytesIO(data)).pages))
    return out


def mosque_shown(at):
    tables = " ".join(" ".join(map(str, d.value.columns)) + " " + " ".join(map(str, d.value.index)) for d in at.dataframe)
    # Mosque information = names, counts or distances; the census note "not where mosques ... are" is not mosque information
    return bool(re.search(r"mapped mosque|Mosques \(mapped\)|Mosque inside|Mosque \(km\)|Km to mosque|Mosque: [\d.]+ km|Mosques mapped inside",
                          text(at) + tables, re.I))


pick2 = lambda a: widget(a.multiselect, "Compare suburbs").set_value([av_name, "Queen Street"])  # noqa: E731
pages = [("Family screen", None, None), ("Find a rental under my budget", None,
                                         lambda a: widget(a.number_input, "My budget ($ a week)").set_value(800)),
         ("Suburb in plain English", av_name, None), ("Explore suburb", av_name, None), ("Compare suburbs", None, pick2)]
for view, sub, setup in pages:
    off, on_ = run(view, suburb=sub, setup=setup), run(view, suburb=sub, setup=setup, mosques=True)
    check(f"Mosque info hidden by default, shown when enabled: {view}", not mosque_shown(off) and mosque_shown(on_))
    if view == "Explore suburb":
        r_off, r_on = reports(off), reports(on_)
        check("Downloads (PDF and Word): mosque row only when enabled; reports still build",
              len(r_off) == 2 and not any("Mosques (mapped)" in t for t in r_off.values())
              and all("Mosques (mapped): 1 inside the area" in t for t in r_on.values()))
    if view == "Compare suburbs":
        tab = [d.value for d in on_.dataframe if "Nearest mapped mosque" in d.value.index][0]
        check("Compare (enabled): nearest mosque agrees with the profile",
              tab.loc["Nearest mapped mosque", av_name] == f"{prof.loc[av_name, 'nearest_mosque']}, {prof.loc[av_name, 'km_to_nearest_mosque']:.1f} km")
opts = lambda at: widget(at.selectbox, "Metric").options  # noqa: E731
check("Map lab: mosque distance metric offered only when enabled",
      "Mosque distance (km)" not in opts(run("Map lab")) and "Mosque distance (km)" in opts(run("Map lab", mosques=True)))
fam = [d.value for d in run("Family screen", setup=lambda a: widget(a.number_input, "Budget ($/wk)").set_value(900)).dataframe][0]
check("Family screen default sort is rent, lowest first (not a community share)",
      fam["Rent $/wk"].is_monotonic_increasing and not any(c.endswith(" %") for c in fam.columns), f"{len(fam)} rows")

# Missing values: an analysis-ready area with no rent
at = run("Suburb in plain English", suburb="Ararimu")
check("Missing rent shown as 'no figure', not zero (Ararimu)", "Rent: no figure" in text(at) and not at.exception)

# Unranked areas stay out of Opportunity finder unless asked for
at = run("Opportunity finder")
n0 = int(kpi(at, "Matches")[0])
ranks = [d.value for d in at.dataframe if "Screen rank" in d.value.columns][0]["Screen rank"]
at2 = run("Opportunity finder", setup=lambda a: widget(a.checkbox, "Also show unranked areas (risk unknown)").check())
check("Opportunity finder: default list is ranked areas only; unranked appear only when ticked",
      ranks.notna().all() and int(kpi(at2, "Matches")[0]) > n0, f"default {n0}, with unranked {kpi(at2, 'Matches')[0]}")

# Forecast labelled experimental, with the benchmark beside it
at = run("Explore suburb", suburb="Pukekohe West")
t = text(at)
check("Explore: scenario labelled experimental, unchanged-rent benchmark and test results shown",
      "Experimental Auckland-trend scenario" in t and "unchanged" in kpi(at, "Scenario, year 1")[1]
      and "4.7% against 5.0%" in t and "held 79%" in t and "80% band" not in t)
at = run("Data & Methods")
check("Data & Methods: refresh date, SA2 note, sources and forecast test table",
      f"Data last refreshed" in text(at) and "Areas are not suburbs" in text(at) and len(at.dataframe) == 1 and len(at.expander) == 5)

# ---------- report ----------
width = max(len(n) for n, _, _ in results)
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail if not ok else ''}")
failed = sum(not ok for _, ok, _ in results)
print(f"\n{len(results) - failed} of {len(results)} checks passed")
sys.exit(1 if failed else 0)
