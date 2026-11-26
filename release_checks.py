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


def run(view, suburb=None, setup=None, mosques=False, level="sa2"):  # the SA2 checks below pin level; suburb checks at the end
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["level"] = level
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
    return html.unescape("\n".join(str(e.value) for e in list(at.markdown) + list(at.caption) + list(at.info) + list(at.warning) + list(at.error)))


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
VIEWS = ["Overview", "Ask Auckland", "Rent in Auckland", "Explore suburb", "Compare suburbs", "Opportunity finder", "Map lab", "Suburb in plain English",
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
      bool(ok) and len(ok[0]) > 0 and (ok[0]["Source-area bonds (12 months)"] >= 30).all() and "average of Oct 2025–Sep 2026" in text(at),
      f"rows {len(ok[0]) if ok else 0}")

# The shared search (search.py) the AI chat will call gives the same answers as the pages
import search  # noqa: E402

data = search.load_data("sa2")
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
    # Reports are read straight after each run: a run's download files can be cleaned up once later runs start (seen on Streamlit 1.67)
    off = run(view, suburb=sub, setup=setup)
    r_off = reports(off) if view == "Explore suburb" else None
    on_ = run(view, suburb=sub, setup=setup, mosques=True)
    r_on = reports(on_) if view == "Explore suburb" else None
    check(f"Mosque info hidden by default, shown when enabled: {view}", not mosque_shown(off) and mosque_shown(on_))
    if view == "Explore suburb":
        check("Downloads (PDF and Word): mosque row only when enabled; reports still build",
              len(r_off) == 2 and not any("Mosques (mapped)" in t for t in r_off.values())
              and all("Mosques (mapped): 1 inside the SA2" in t for t in r_on.values()))
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
      f"Data last refreshed" in text(at) and "Areas are not suburbs" in text(at) and len(at.dataframe) == 1 and len(at.expander) == 6)

# ---------- Ask Auckland: chat and manual searches agree ----------
# Gemini is replaced by stubs that return fixed filters, so these checks use no API quota; the reply itself is computed by chat.py
import chat  # noqa: E402
from google.genai import errors  # noqa: E402
from pydantic import ValidationError  # noqa: E402

A = chat.Ask


def ask(*answers, key="test-key", mosques=False, messages=None, level="sa2"):  # messages: when a retry uses two answers for one message
    it = iter(answers)

    def fake(client, q, prefs, history):
        a = next(it)
        if isinstance(a, Exception):
            raise a
        return a
    chat.gemini_extract = fake  # app.py calls chat.gemini_extract, so the page uses the stub
    at = AppTest.from_file("app.py", default_timeout=180)
    at.session_state["show_mosques"] = mosques
    at.session_state["level"] = level
    at.session_state["view"] = "Ask Auckland"
    at.secrets["GEMINI_API_KEY"] = key  # "" = no key (overrides a local secrets.toml)
    at.run()
    for _ in range(messages or len(answers)):
        at.chat_input[0].set_value("a question").run()
    return at


def table(at, col):
    return [d.value for d in at.dataframe if col in d.value.columns]


home3 = "Rent $/wk (3-bedroom house)"
c = ask(A(intent="rental_search", max_rent=600, dwelling="House", beds="3"))
m = run("Find a rental under my budget")
cf, mf = table(c, "Rent covers"), table(m, "Rent covers")
check("Chat = manual, zero-match $600 3-bed house: says no match, same 13 areas and broader rents",
      not c.exception and "No area matches" in text(c) and home3 not in " ".join(map(str, sum((list(d.value.columns) for d in c.dataframe), [])))
      and bool(cf and mf) and cf[0]["Area"].tolist() == mf[0]["Area"].tolist() and cf[0]["Broader rent $/wk"].tolist() == mf[0]["Broader rent"].tolist(),
      f"chat {len(cf[0]) if cf else 0}, manual {len(mf[0]) if mf else 0}")
c = ask(A(intent="rental_search", max_rent=700, dwelling="House", beds="3"))
m = run("Find a rental under my budget", setup=lambda a: widget(a.number_input, "My budget ($ a week)").set_value(700))
cm, mm = table(c, home3), table(m, "Quarters with data (of 4)")
check("Chat = manual, $700 3-bed house: same budget-match areas, rents and lodgement counts",
      bool(cm and mm) and cm[0]["Area"].tolist() == mm[0]["Area"].tolist() and cm[0][home3].tolist() == mm[0]["Typical rent"].tolist()
      and cm[0]["Source-area bonds (12 months)"].tolist() == mm[0]["Source-area bonds (12 months)"].tolist(), f"chat {len(cm[0]) if cm else 0}, manual {len(mm[0]) if mm else 0}")
check("Chat answers always show sample check, crime, schools, GPs and shopping centres with the rent period; nothing else unasked",
      bool(cm) and {"Sample check", "Crime per 1,000 residents", "Crime rating", "Primary schools in area", "GP clinics in area",
                    "Nearest shopping centre"} <= set(cm[0].columns) and not {"Parks in area", "Muslim residents % (2023 Census)"} & set(cm[0].columns)
      and "(Oct 2025–Sep 2026)" in text(c) and "30+ new bonds" in text(c))
c = ask(A(intent="rental_search", max_rent=580, dwelling="House", beds="3"))
check("Chat = Family screen reference ($580 3-bed house): 0 matches, 4 under budget that fail the checks, 138 with no figure",
      "No area matches" in text(c) and "4 more areas have a figure under budget that fails" in text(c) and "138 areas have no published rent" in text(c))
c = ask(A(intent="rental_search", max_rent=600, dwelling="House", beds="3"), A(intent="rental_search", beds="2"))
c2 = table(c, "Rent $/wk (2-bedroom house)")
check("Follow-up keeps budget and home type: 'what about 2 bedrooms' searches 2-bed houses up to $600",
      c.session_state["ask_prefs"] == {"max_rent": 600, "dwelling": "House", "beds": "2", "intent": "rental_search"} and bool(c2)
      and c2[0]["Area"].tolist() == search.rental_search(data, 600, "House", "2")["matches"]["sa2_name"].tolist())
c = ask(A(intent="rental_search", dwelling="House", beds="3", low_crime=True, school=True))
cl = table(c, home3)
base = search.rental_search(data, 100_000, "House", "3")["matches"]
want = base[base["crime_rating"].eq("Low") & base["primary_schools_in_area"].gt(0)]["sa2_name"].tolist()
check("Plain-English list: 'safe suburbs with schools, 3-bed house' (no budget) lists low-crime areas with a primary school, cheapest first",
      bool(cl) and cl[0]["Area"].tolist() == want and "No budget given" in text(c) and "Cheapest: " + want[0] in text(c), f"{len(cl[0]) if cl else 0} vs {len(want)}")
c = ask(A(intent="compare", areas=["Avondale Central", "Queen Street"]))
m = run("Compare suburbs", setup=pick2)
ct, mt = table(c, "Rent $/wk (home)"), [d.value for d in m.dataframe if "Weekly rent (new tenancies)" in d.value.index]
check("Chat compare = Compare page: all-home rent and crime per 1,000 for Avondale Central and Queen Street",
      bool(ct and mt) and [f"${v:,.0f}" for v in ct[0]["Rent $/wk (home)"]] == mt[0].loc["Weekly rent (new tenancies)"].tolist()
      and [f"{v:.0f}" for v in ct[0]["Crime per 1,000 residents"]] == mt[0].loc["Crime /1,000 residents"].tolist())
c = ask(A(intent="area_info", areas=["Mt Roskill"]))
check("Chat asks which area when a name matches more than 8 SA2s (Mt Roskill, 10)", "Which one do you mean?" in text(c) and not c.dataframe)
c = ask(A(intent="area_info", areas=["Avondale Central"]), A(intent="rental_search", max_rent=800, dwelling="House", beds="3"), mosques=True)
check("Chat leaves mosque information out unless asked (even with the toggle on)", not mosque_shown(c))
c3 = ask(A(intent="rental_search", dwelling="ALL", beds="2", min_muslim_pct=5, near_mosque=True, near_halal=True))
c3t = table(c3, "Nearest mapped mosque")
ref = search.rental_search(data, 100_000, "ALL", "2")["matches"]
ref = ref[ref["pct_muslim"].gt(5) & ref["km_to_nearest_mosque"].le(3) & (ref["halal_places_in_area"].gt(0) | ref["halal_butchers_in_area"].gt(0)
          | ref["km_to_nearest_halal_butcher"].le(3))]
p3 = prof.loc[ref["sa2_name"]]
check(f"'2-bed house/unit, over 5% Muslim, near a mosque and halal shops': {len(ref)} areas, Muslim %, mosque and halal as in the area profile",
      bool(c3t) and c3t[0]["Area"].tolist() == ref["sa2_name"].tolist() and (c3t[0]["Nearest mapped mosque"].values == p3["nearest_mosque"].values).all()
      and (c3t[0]["Mosque km (straight-line)"].values == p3["km_to_nearest_mosque"].values).all()
      and c3t[0]["Muslim residents % (2023 Census)"].gt(5).all() and "Halal butchers mapped inside" in c3t[0]
      and "list is partial" in text(c3) and "Census shares show where people live" in text(c3), f"{len(c3t[0]) if c3t else 0} vs {len(ref)}")
quota = errors.ClientError(429, {"error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}})
c = ask(quota)
btn = [b for b in c.button if b.label == "Open Find a rental under my budget"]
check("API limit (429): clear message and buttons to the manual filters", "free AI usage limit" in text(c) and len(btn) == 1 and not c.exception)
btn[0].click().run() if btn else None
check("API limit button opens the manual search", c.session_state["view"] == "Find a rental under my budget")
busy = errors.ServerError(503, {"error": {"code": 503, "message": "The model is overloaded", "status": "UNAVAILABLE"}})
c = ask(busy, A(intent="rental_search", max_rent=600, dwelling="House", beds="3"), messages=1)
c2 = ask(busy, busy, busy, messages=1)
check(f"Gemini 503: retried and answered; after {chat.RETRIES} retries says try again and offers manual filters",
      "No area matches" in text(c) and "try again in a moment" in text(c2) and any(b.label.startswith("Open Find") for b in c2.button))
try:
    A.model_validate_json('{"intent": "nonsense"}')
except ValidationError as e:
    bad = e
check("Malformed model output: asks to rephrase, offers manual filters", "couldn't turn that into a search" in text(ask(bad)))
c = ask(A(intent="other"), key="")
check("No API key: chat says it isn't set up and the page still works", "isn't set up" in text(c) and not c.exception)

# ---------- suburb level (the dashboard default) ----------
sub = search.load_data()
S2 = sub["sa2"]
at = AppTest.from_file("app.py", default_timeout=180)
at.run()
check("Suburb level is the default: sidebar lists suburbs, Auckland Central selected",
      at.session_state["level"] == "suburb" and widget(at.selectbox, "Suburb").value == "Auckland Central" and len(widget(at.selectbox, "Suburb").options) == len(S2))
c = ask(A(intent="rental_search", max_rent=700, dwelling="House", beds="3"), level="suburb")
m = run("Find a rental under my budget", setup=lambda a: widget(a.number_input, "My budget ($ a week)").set_value(700), level="suburb")
cm, mm = table(c, home3), table(m, "Quarters with data (of 4)")
ref = search.rental_search(sub, 700, "House", "3")["matches"]
check("Suburb level, chat = manual = shared search ($700 3-bed house): same suburbs, rents and lodgements",
      bool(cm and mm) and cm[0]["Area"].tolist() == mm[0]["Area"].tolist() == ref["sa2_name"].tolist()
      and cm[0][home3].tolist() == mm[0]["Typical rent"].tolist() and "LINZ suburbs" in text(c), f"chat {len(cm[0]) if cm else 0}, manual {len(mm[0]) if mm else 0}")
c = ask(A(intent="area_info", areas=["Ponsonby East"]), level="suburb")
check("Suburb level chat: an SA2 name finds its suburb (Ponsonby East -> Ponsonby)", table(c, "Rent $/wk (home)")[0]["Area"].tolist() == ["Ponsonby"])
at = run("Explore suburb", suburb="Papatoetoe", level="suburb")
parts = [d.value for d in at.dataframe if "SA2 area" in d.value.columns]
codes = S2.set_index("sa2_name").loc["Papatoetoe", "sa2_codes"].split(";")
check("Explore suburb: SA2 parts drill-down lists every SA2 of the suburb (Papatoetoe)",
      bool(parts) and len(parts[0]) == len(codes) and parts[0]["Residents 2023"].sum() == S2.set_index("sa2_name").loc["Papatoetoe", "population_2023"],
      f"{len(parts[0]) if parts else 0} vs {len(codes)}")
import json  # noqa: E402
ids = {f["properties"]["suburb_id"] for f in json.load(open("data/boundaries/auckland_suburbs_map.geojson", encoding="utf-8"))["features"]}
check("Suburb map: one polygon per suburb row", ids == set(S2["sa2_code"]), f"{len(ids)} polygons, {len(S2)} rows")
at = run("Suburb in plain English", suburb=S2[S2["analysis_ready"] & S2["mosques_in_area"].eq(0)]["sa2_name"].iloc[0], mosques=True, level="suburb")
check("Suburb level zero-mosque wording says 'this suburb'", "No mosque mapped inside this suburb" in text(at) and "this SA2" not in text(at))
check("Suburb screen: shared-SA2 places are never ranked", S2.loc[S2["suburb_source_sa2"].notna(), "ranked"].ne(True).all())

# ---------- audit of b3f2aaa: geography, shared areas, benchmarks, rent provenance, rent quality, chat hardening ----------
import os  # noqa: E402

import geopandas as gpd  # noqa: E402

from build_suburbs import rate_crime  # noqa: E402

LINZ = "data/boundaries/auckland_suburbs_linz.geojson"  # raw LINZ file, not in git (27 MB); download_data.py fetches it
prof_s = pd.read_csv(f"{CLEAN}/suburb_profiles.csv").set_index("suburb_name")
if os.path.exists(LINZ):
    # Independent recount: raw point files and the raw LINZ polygons, without facilities.py or build_suburbs.py
    poly = gpd.read_file(LINZ).to_crs(2193)[["id", "geometry"]].rename(columns={"id": "suburb_id"})
    poly["geometry"] = poly.make_valid()
    gp = pd.read_csv("data/amenities/gp_clinics_auckland.csv")
    gp = gp[~gp["osm_id"].isin(pd.read_csv("data/amenities/gp_clinic_corrections.csv").query("decision == 'drop'")["osm_id"])]
    mq = pd.concat([pd.read_csv("data/amenities/mosques_verified.csv").query("status == 'verified'"),
                    pd.read_csv("data/amenities/mosques_osm_candidates.csv").query("status == 'keep'")])
    pts = {"gp_clinics_in_area": gp, "mosques_in_area": mq, "playgrounds_in_area": pd.read_csv("data/amenities/playgrounds_auckland.csv"),
           "parks_in_area": pd.read_csv("data/amenities/parks_auckland.csv"),
           "supermarkets_in_area": pd.read_csv("data/amenities/supermarkets_auckland.csv"),
           "shopping_centres_in_area": pd.read_csv("data/amenities/shopping_centres_auckland.csv"),
           "halal_places_in_area": pd.read_csv("data/amenities/halal_shops_auckland.csv")}
    ids = prof_s.reset_index().set_index("suburb_id")
    bad = {}
    for col, d in pts.items():
        g = gpd.GeoDataFrame(geometry=gpd.points_from_xy(d["lon"], d["lat"]), crs=4326).to_crs(2193)
        n = gpd.sjoin(g, poly, predicate="within").groupby("suburb_id").size().reindex(ids.index, fill_value=0)
        bad[col] = int((n != ids[col]).sum())
    check("Boundary = counts: facilities recounted independently inside the LINZ boundaries match every suburb (7 measures)",
          sum(bad.values()) == 0, str(bad))
else:
    check("Boundary = counts: raw LINZ boundary file present for the independent recount", False, f"{LINZ} missing: run download_data.py")
w = prof_s.loc["Wai o Taiki Bay"]
check("Wai o Taiki Bay: 0 GPs inside its LINZ boundary (1 in its assigned SA2 is kept as gp_clinics_in_assigned_sa2s)",
      (w["gp_clinics_in_area"], w["gp_clinics_in_assigned_sa2s"]) == (0, 1))
corr = pd.read_csv("data/amenities/gp_clinic_corrections.csv")
names = set(pd.read_csv("data/amenities/gp_clinics_auckland.csv").query("osm_id in @corr.osm_id")["name"].dropna())
check("GP corrections: reviewed list with reasons; specialists (e.g. Franklin Cardiology) dropped and absent from nearest-GP names",
      corr["reason"].notna().all() and {"Epsom Anaesthetic Group", "Franklin Cardiology", "Mark Gittos Plastic Surgery"} <= set(corr.query("decision == 'drop'")["name"])
      and not set(corr.query("decision == 'drop'")["name"]) & set(prof_s["nearest_gp_clinic"]) and names <= set(corr["name"].dropna()))

# shared areas: 70 borrowed rows, each with its source SA2 and the disclosure wording
b = prof_s[prof_s["coverage"] == "borrowed"]
check("Shared areas: 70 places borrow a parent SA2; each names its source SA2 and carries the wider-area wording",
      len(b) == 70 and b["coverage_source_name"].notna().all()
      and b["coverage_note"].str.startswith("Wider-area estimate—covers neighbouring places").all())
z = search.rental_search(sub, 700, "House", "3")
check("$700 3-bed house (suburbs): borrowed places are separated from budget matches (4 that pass checks, listed apart)",
      z["matches"]["independent"].all() and (z["shared"]["check"] == "ok").sum() == 4 and not z["shared"]["independent"].any())
m = run("Find a rental under my budget", setup=lambda a: widget(a.number_input, "My budget ($ a week)").set_value(700), level="suburb")
shared_t = [d.value for d in m.dataframe if "Covers (SA2)" in d.value.columns]
check("Find a rental (suburbs): wider-area estimates shown in their own table with the source SA2",
      "Wider-area estimates under budget" in text(m) and bool(shared_t) and set(shared_t[0]["Area"]) == set(z["shared"]["sa2_name"]))
c = ask(A(intent="rental_search", max_rent=700, dwelling="House", beds="3"), level="suburb")
check("Chat (suburbs): wider-area estimates in a separate table; every table has a Coverage column",
      any("Wider-area estimates" in str(e.value) for e in c.markdown) and all("Coverage" in d.value.columns for d in c.dataframe))
at = run("Explore suburb", suburb="Waiake", level="suburb")
rw = reports(at)
check("Explore Waiake: wider-area warning names Torbay and the SA2 beside the figures, and in both reports",
      "Wider-area estimate—covers neighbouring places" in text(at) and "Torbay" in text(at)
      and len(rw) == 2 and all("Wider-area estimate" in t for t in rw.values()))
at = run("Suburb in plain English", suburb="Waiake", level="suburb")
check("Plain English Waiake: wider-area warning shown (not only the shared-rent note)", "Wider-area estimate—covers neighbouring places" in text(at))
at = run("Compare suburbs", level="suburb", setup=lambda a: widget(a.multiselect, "Compare suburbs").set_value(["Waiake", "Torbay"]))
ct = [d.value for d in at.dataframe if "Coverage" in d.value.index]
check("Compare: Coverage row marks Waiake as a wider-area estimate and Torbay as own SA2s",
      bool(ct) and ct[0].loc["Coverage", "Waiake"].startswith("Wider-area estimate") and ct[0].loc["Coverage", "Torbay"] == "Own SA2s")
at = run("Map lab", suburb="Waiake", level="suburb")
check("Map lab (suburbs): borrowed places uncoloured and unranked; LINZ and SA2 analysis outlines explained",
      "Not ranked on this map: wider-area estimate" in text(at) and "amber = the Stats NZ SA2 areas" in text(at) and not at.exception)

# benchmarks from independent rows: adding or removing a borrowed row moves nobody else's crime rating, CV median or rank
cr = prof_s.reset_index()
ind = cr["coverage"].ne("borrowed")
base_r = rate_crime(cr, ind)
fake = cr[ind & cr["analysis_ready"]].nlargest(1, "crime_per_1000_residents").assign(crime_per_1000_residents=1e6, suburb_name="Fake alias")
plus = pd.concat([cr, fake], ignore_index=True)
check("Benchmark invariance: crime ratings unchanged when borrowed rows are removed or an extreme alias is added",
      base_r[ind].equals(rate_crime(cr[ind], ind[ind])) and rate_crime(plus, plus["coverage"].ne("borrowed") & ~plus.index.isin([len(cr)]))[:len(cr)][ind].equals(base_r[ind])
      and prof_s["crime_rating"].reset_index(drop=True)[ind].equals(base_r[ind]))
own_med = cr.loc[ind & cr["analysis_ready"], "cv_change_2021_2024_pct"].median()
at = run("Overview", level="suburb")
check(f"Overview CV median uses suburbs with their own SA2s ({own_med:+.2f}%, not the {cr.loc[cr['analysis_ready'], 'cv_change_2021_2024_pct'].median():+.2f}% with borrowed rows)",
      kpi(at, "CV change 2021–24")[0] == f"{own_med:+.2f}%", str(kpi(at, "CV change 2021–24")))

# rent provenance: real MBIE ids, shared series counted once, source vs apportioned bonds
src = pd.read_csv(f"{CLEAN}/suburb_rent_sources.csv")
mbie = set(sa2["rent_source_sa2"].dropna().astype(int))
key = S2.set_index("sa2_name")["rent_source_sa2"]
main = src[src["own_sa2"]]
check("MBIE sources: every source id is a real MBIE rent area; Arkles Bay and Wade Heads share 114900; apportioned bonds add back to MBIE totals",
      set(src["rent_source_sa2"]) <= mbie and key["Arkles Bay"] == key["Wade Heads"] == "114900"
      and (main.groupby("rent_source_sa2")["apportioned_lodged_4q"].sum() - main.groupby("rent_source_sa2")["source_lodged_4q"].first()).abs().max() < 1e-6)
at = run("Rent in Auckland", suburb="Tōtara Park", level="suburb")
rt = [d.value for d in at.dataframe if "Est. bonds apportioned (estimate)" in d.value.columns]
h3 = rt[0].set_index("Home").loc["3-bedroom house"] if rt else None
check("Tōtara Park 3-bed house: 45 source-area bonds and about 7.9 apportioned, labelled separately",
      h3 is not None and h3["Source-area bonds (12 months)"] == 45 and round(h3["Est. bonds apportioned (estimate)"], 1) == 7.9)

# rent quality: failing figures are never green or 'cheaper than most', everywhere they appear
at = run("Suburb in plain English", suburb="Cornwallis", level="suburb")
t = text(at)
check("Cornwallis (18 bonds, unstable): plain English shows 'fails sample checks', no 'cheaper than most', no green",
      "fails sample checks" in t and "cheaper than most" not in t and "18 source-area bonds" in t)
at = run("Explore suburb", suburb="Cornwallis", level="suburb")
check("Cornwallis Explore: rent KPI flagged, warning beside it, badge shown",
      "(fails sample checks)" in kpi(at, "Weekly rent")[0] and "Rent fails sample checks" in text(at) and "18 source-area bonds" in text(at))
c = ask(A(intent="area_info", areas=["Cornwallis"]), level="suburb")
check("Chat Cornwallis: sample check says it fails", "Fails sample checks" in " ".join(table(c, "Sample check")[0]["Sample check"].astype(str)))

# exceptional places, one-bedroom note, missing data
for name, phrase in [("Huntington Park", "6 census residents"), ("Mangawhai", "Northland")]:
    at = run("Explore suburb", suburb=name, level="suburb")
    c = ask(A(intent="area_info", areas=[name]), level="suburb")
    check(f"{name}: prominent warning on Explore and in chat", phrase in text(at) and phrase in text(c))
c = ask(A(intent="rental_search", max_rent=500, beds="1"), level="suburb")
check("Chat carries the one-bedroom data warning", "one-bedroom counts and rents with caution" in text(c))
scr = pd.read_csv(f"{CLEAN}/suburb_screen.csv")
check("Missing data stays missing: 18 screened suburbs without volatility are unranked with that reason, not filled",
      (scr["missing_inputs"].fillna("").str.contains("rent_volatility") & ~scr["ranked"]).sum() == 18 and scr.loc[scr["ranked"], "rent_volatility"].notna().all())

# mapping reproducibility
lk = pd.read_csv(f"{CLEAN}/sa2_to_suburb.csv")
check("Mapping: 633 lookup rows kept; 6 water SA2s are reviewed exclusions (confidence 'not applicable', reasons kept); "
      "Inlet Waitematā Harbour keeps its 3 residents in the SA2 data",
      len(lk) == 633 and (lk["match_rule"] == "excluded").sum() == 6
      and lk.loc[lk["match_rule"] == "excluded", "boundary_confidence"].eq("not applicable (reviewed exclusion)").all()
      and lk.loc[lk["match_rule"] == "excluded", "exclusion_reason"].notna().all()
      and sa2.set_index("sa2_code").loc[119301, "population_2023"] == 3)
if os.path.exists(LINZ):
    import review_evidence  # noqa: E402
    rv = pd.read_csv("data/boundaries/sa2_to_suburb_review.csv", encoding="utf-8-sig")
    diff = review_evidence.compare(rv, review_evidence.evidence(rv["sa2_code"]))
    check("Review evidence regenerated for all 50 reviewed SA2s (SA1 residents, rating units, council addresses) matches the committed review",
          diff.empty, diff.to_string()[:300])

# app helpers (were import-time asserts in app.py), compiled from app.py without running the page
import ast  # noqa: E402
from urllib.parse import quote  # noqa: E402

with open("app.py", encoding="utf-8") as fh:
    _tree = ast.parse(fh.read())
_ns = {"quote": quote, "SUB": False}
exec(compile(ast.Module([n for n in _tree.body if isinstance(n, ast.FunctionDef) and n.name in ("suburb_word", "listings_url")], []),
             "app.py", "exec"), _ns)
sw, lu = _ns["suburb_word"], _ns["listings_url"]
check("Trade Me helpers: suburb word from SA2 names, search URL carries budget, beds and type",
      sw("Glen Innes East-Wai O Taiki Bay") == "Glen Innes" and sw("Massey Central") == "Massey"
      and sw("Te Atatū Peninsula West") == "Te Atatū Peninsula" and sw("Āwhitu") == "Āwhitu"
      and lu("Pukekohe", "House", "3", 600).endswith("search_string=Pukekohe&price_max=600&bedrooms_min=3&bedrooms_max=3&property_type=house"))
_p = pd.read_csv(f"{CLEAN}/suburb_profiles.csv").set_index("suburb_name")
check("Huntington Park and Mangawhai caveat column leads with their warning",
      _p.loc["Huntington Park", "caveat"].startswith("Statistical coverage is tiny") and _p.loc["Mangawhai", "caveat"].startswith("Mostly outside Auckland"))
at = run("Opportunity finder", level="suburb")
check("Opportunity 'MBIE rent areas' counts the source ids behind the matches (288), not id combinations (93)",
      not at.exception and kpi(at, "MBIE rent areas")[0] == "288", str(kpi(at, "MBIE rent areas")))
at = run("Explore suburb", "Newmarket", level="suburb")
check("Commercial / mixed units badge (rating units > 1.4 per dwelling) on Explore: Newmarket",
      not at.exception and "Commercial / mixed units" in "".join(m.value for m in at.markdown), f"{(_p.units_per_dwelling > 1.4).sum()} suburbs carry it")

# chat hardening: timeout recovery, validation, usage caps, geography in history
import httpx2  # noqa: E402  google-genai's default HTTP backend from 3.6

c = ask(*[httpx2.ReadTimeout("timed out")] * (chat.RETRIES + 1), messages=1)
check("Chat timeout (httpx2.ReadTimeout, the SDK's default backend, after retries): clear message and manual fallback, no crash",
      not c.exception and "timed out" in text(c) and any(b.label.startswith("Open Find") for b in c.button))
check("Chat usage caps count every Gemini request: one question with 2 retries uses 3", c.session_state["ask_used"] == chat.RETRIES + 1,
      str(c.session_state["ask_used"]))
c = ask(A(intent="rental_search", max_rent=-5))
check("Chat validation: a negative budget is refused, not searched", "Please give a weekly budget above" in text(c) and not c.dataframe)
at = AppTest.from_file("app.py", default_timeout=180)
at.session_state["view"], at.session_state["ask_used"] = "Ask Auckland", chat.SESSION_LIMIT
at.secrets["GEMINI_API_KEY"] = "test-key"
chat.gemini_extract = lambda *a: (_ for _ in ()).throw(AssertionError("Gemini must not be called over the cap"))
at.run()
at.chat_input[0].set_value("a question").run()
check(f"Chat usage cap: after {chat.SESSION_LIMIT} AI requests in a session, no Gemini call; manual fallback offered",
      not at.exception and f"used {chat.SESSION_LIMIT} AI requests" in text(at))
c = ask(A(intent="area_info", areas=["Ponsonby"]), level="suburb")
c.session_state["level"] = "sa2"
c.run()
check("Chat history marks the geography and says when it switches", "Figures for LINZ suburbs" in text(c) and "Switched to Stats NZ SA2 areas" in text(c))

# ---------- report ----------
width = max(len(n) for n, _, _ in results)
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail if not ok else ''}")
failed = sum(not ok for _, ok, _ in results)
print(f"\n{len(results) - failed} of {len(results)} checks passed")
sys.exit(1 if failed else 0)
