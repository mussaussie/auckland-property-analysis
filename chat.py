"""Ask Auckland: Gemini reads the question, search.py answers it.

The model only turns a message into filters (intent, budget, home type, bedrooms, area names). Every figure, table and
caveat in the reply is built here from data/clean with the same functions the manual pages use (search.py), so a chat
search and a manual search with the same filters give the same areas and rents.
Self-check (no API call): python chat.py
"""
import json
import re
import time
import unicodedata
from typing import Literal, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from search import rent_period, rental_search, with_home_rent

MODEL = "gemini-3.5-flash-lite"  # free tier about 500 requests/day (Nov 2026); Flash is about 20/day. One request per question.
TIMEOUT_MS = 20_000   # per Gemini request; a hung connection ends as a timeout error (httpx2 backend) and the manual fallback is shown
RETRIES = 2           # extra tries for 5xx and network errors only (a 429 quota error is never retried)
SESSION_LIMIT = 30    # questions per browser session
DAILY_LIMIT = 400     # questions per day for the whole app, under the ~500/day free quota


def make_client(key):
    from google import genai
    from google.genai import types
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))


def net_errors():
    """Network error classes of the HTTP backends google-genai may use: httpx2 (its default from 3.6) and httpx (fallback)."""
    import importlib
    out = []
    for m in ("httpx2", "httpx"):
        try:
            out.append(importlib.import_module(m).TransportError)
        except ImportError:
            pass
    return tuple(out)


def with_retries(fn, *a, retries=RETRIES, sleep=time.sleep):
    """fn(*a), retried with a short back-off on Google 5xx errors and network failures (timeouts, dropped connections)."""
    from google.genai import errors
    for i in range(retries + 1):
        try:
            return fn(*a)
        except (errors.ServerError, *net_errors()):
            if i == retries:
                raise
            sleep(2 * (i + 1))


def over_limit(used_session, used_today):
    """Message when a usage cap is reached, else None."""
    if used_session >= SESSION_LIMIT:
        return (f"You have asked {SESSION_LIMIT} questions in this session, the limit that protects the shared free AI quota. "
                "Reload the page later, or use the manual filters:")
    if used_today >= DAILY_LIMIT:
        return "Ask Auckland has reached its daily question limit (shared free AI quota). It resets tomorrow; the manual filters give the same results:"


EXTRAS = Literal["muslim", "mosque", "halal", "park", "playground", "supermarket"]


class Ask(BaseModel):
    intent: Literal["rental_search", "area_info", "compare", "clarify", "other"]
    max_rent: Optional[int] = Field(None, description="Weekly rent budget in NZ dollars, only if stated in this message")
    dwelling: Optional[Literal["House", "Apartment", "Flat", "ALL"]] = Field(None, description="Home type, only if stated in this message")
    beds: Optional[Literal["1", "2", "3", "4", "5+", "ALL"]] = Field(None, description="Bedrooms, only if stated in this message")
    include_apt: Optional[bool] = Field(None, description="True only if the user asks to include apartments or the city centre")
    low_crime: Optional[bool] = Field(None, description="True if the user wants safe / low-crime areas; false if they drop that wish")
    school: Optional[bool] = Field(None, description="True if the user wants a (primary) school in the area; false if they drop it")
    park: Optional[bool] = Field(None, description="True if the user wants parks or green space in the area; false if they drop it")
    min_muslim_pct: Optional[float] = Field(None, description="Minimum % of residents who are Muslim, only if stated; 0 drops the wish")
    near_mosque: Optional[bool] = Field(None, description="True if the user wants a mosque nearby; false if they drop it")
    near_halal: Optional[bool] = Field(None, description="True if the user wants halal shops or food nearby; false if they drop it")
    near_km: Optional[float] = Field(None, description="Distance in km for 'nearby', only if stated ('within 2 km')")
    show: list[EXTRAS] = Field(default_factory=list, description="Extra facts the user asks to see without filtering on them")
    areas: list[str] = Field(default_factory=list, description="Suburb or area names as the user wrote them in this message")
    question: Optional[str] = Field(None, description="When intent is clarify: one short question for the user")


SYSTEM = """You turn messages about renting in Auckland, New Zealand into search filters for a dashboard.
Never answer the question yourself and never give figures: return only JSON that matches the schema.
intent:
- rental_search: any request for a list of suburbs or areas to rent in: by budget, home type, bedrooms, safety (low_crime),
  schools (school), parks (park), Muslim share of residents (min_muslim_pct), a nearby mosque (near_mosque), nearby halal
  shops or food (near_halal) or a place. A budget is optional ("safe suburbs with schools for a 3 bed house").
- area_info: facts about one named area (rent, crime, schools, GPs, shops, whether it fits a budget).
- compare: two or more named areas side by side.
- clarify: too vague to search, e.g. "where should I live?" with no budget or area; put one short question in `question`.
- other: anything else (house sale prices, forecasts, investment advice, other cities, small talk).
Filters: max_rent is NZ$ per week (monthly x 12 / 52, fortnightly / 2). dwelling: House, Apartment, Flat (flat or unit) or ALL (any home).
When the message names two or more home types ("house/unit", "house or apartment"), dwelling is ALL, never just one of them.
beds: "1" to "4", "5+" or "ALL"; a studio is "1".
areas: suburb names in full, with nicknames expanded (Pt Chev -> Point Chevalier, Grey Lynn stays Grey Lynn). Fill areas for any
intent when the message names a place, including a budget search limited to a place.
Rent, crime, schools, GPs and shopping centres are always shown. show: extra facts asked about but not required ("show the
Muslim %", "how many parks?"): muslim, mosque, halal, park, playground, supermarket. A requirement ("more than 5% Muslim",
"near a mosque") sets the filter field instead.

Follow-ups: the user's current preferences and the recent conversation are given. Set a filter only if this message states or
changes it; leave it null otherwise, so earlier preferences carry over. A short follow-up ("what about 2 bedrooms?", "and $700?")
keeps the previous intent. "Any number of bedrooms" is beds ALL; "any type" is dwelling ALL."""


def gemini_extract(client, question, prefs, history):
    """One Gemini call: message -> Ask. The reply is validated by pydantic, so a malformed one raises instead of being used."""
    from google.genai import types
    talk = "\n".join(f"{who}: {text}" for who, text in history[-6:])
    prompt = f"Current preferences: {json.dumps(prefs)}\nRecent conversation:\n{talk or '(none)'}\nNew message: {question}"
    resp = client.models.generate_content(model=MODEL, contents=prompt, config=types.GenerateContentConfig(
        system_instruction=SYSTEM, response_mime_type="application/json", response_schema=Ask, temperature=0))
    return resp.parsed if isinstance(resp.parsed, Ask) else Ask.model_validate_json(resp.text)


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()  # Māngere == Mangere
    for short, full in (("mt", "mount"), ("st", "saint"), ("pt", "point")):  # SA2 names spell these out: Mt Roskill -> Mount Roskill
        s = re.sub(rf"\b{short}\b\.?", full, s)
    return re.sub(r"\s+", " ", re.sub(r"\(auckland\)", "", s)).strip()


def find_areas(names, text):
    """SA2 names for what the user typed: an exact name, else every SA2 containing it as whole words ('Ponsonby' -> East, West)."""
    t = _norm(text)
    exact = [n for n in names if _norm(n) == t]
    return exact or [n for n in names if re.search(rf"\b{re.escape(t)}\b", _norm(n))]


def area_hits(data, text):
    """Area names at the data's level for what the user typed. Suburb level: suburb names first, else an SA2 name
    ('Ponsonby East') gives the suburb it belongs to."""
    hits = find_areas(sorted(data["sa2"]["sa2_name"]), text)
    if hits or data.get("level") != "suburb":
        return hits
    lk = data["sa2_to_suburb"].dropna(subset=["suburb_name"])
    return sorted(set(lk.set_index("sa2_name").loc[find_areas(sorted(lk["sa2_name"]), text), "suburb_name"]))


def unit(data):
    return "suburb" if data.get("level") == "suburb" else "SA2"


NEAR_KM = 3  # 'nearby' without a stated distance: within 3 km straight-line


def near(p):
    return p.get("near_km") or NEAR_KM


# Optional wishes: (wording, filter on the search's rows, extra columns it shows). Low = lowest third of comparable areas by
# recorded crime per resident. Halal: food places mapped inside, or the nearest halal butcher within the distance.
WANTS = {"low_crime": (lambda p: "low recorded crime", lambda df, p: df["crime_rating"].eq("Low"), None),
         "school": (lambda p: "a primary school inside", lambda df, p: df["primary_schools_in_area"].gt(0), None),
         "park": (lambda p: "a park mapped inside", lambda df, p: df["parks_in_area"].gt(0), "park"),
         "min_muslim_pct": (lambda p: f"more than {p['min_muslim_pct']:g}% Muslim residents",
                            lambda df, p: df["pct_muslim"].gt(p["min_muslim_pct"]), "muslim"),
         "near_mosque": (lambda p: f"a mapped mosque within {near(p):g} km", lambda df, p: df["km_to_nearest_mosque"].le(near(p)), "mosque"),
         "near_halal": (lambda p: f"halal food mapped inside or a halal butcher within {near(p):g} km",
                        lambda df, p: df["halal_places_in_area"].gt(0) | df["halal_butchers_in_area"].gt(0)
                        | df["km_to_nearest_halal_butcher"].le(near(p)), "halal")}

# Extra columns, shown only when asked about or filtered on
EXTRA_COLS = {
    "muslim": {"Muslim residents % (2023 Census)": "pct_muslim"},
    "mosque": {"Nearest mapped mosque": "nearest_mosque", "Mosque km (straight-line)": "km_to_nearest_mosque",
               "Mosque inside area": "mosques_in_area"},
    "halal": {"Halal food places mapped inside": "halal_places_in_area", "Halal butchers mapped inside": "halal_butchers_in_area",
              "Nearest halal butcher km": "km_to_nearest_halal_butcher"},
    "park": {"Parks in area": "parks_in_area", "Nearest park km": "km_to_nearest_park"},
    "playground": {"Playgrounds in area": "playgrounds_in_area", "Nearest playground km": "km_to_nearest_playground"},
    "supermarket": {"Supermarkets in area": "supermarkets_in_area", "Nearest supermarket km": "km_to_nearest_supermarket"}}
EXTRA_NOTES = {
    "muslim": "Muslim % = residents who gave Islam as their religion, 2023 Census. Census shares show where people live, not where "
              "mosques, halal shops or faith schools are.",
    "mosque": "Mosques: 33 mapped (6 verified from a supplied list plus 27 reviewed OpenStreetMap entries). The list is partial and "
              "distances are straight-line from the area's representative point; check other sources for prayer rooms.",
    "halal": "Halal food and butchers come from OpenStreetMap, which is incomplete: 0 means none mapped, not none. Check other "
             "sources before relying on it.",
    "park": "", "playground": "", "supermarket": ""}  # covered by the OpenStreetMap note every answer has
EXTRA_NAMES = {"muslim": "Muslim %", "mosque": "mapped mosques", "halal": "halal food", "park": "parks", "playground": "playgrounds",
               "supermarket": "supermarkets"}


def home_label(dwelling, beds):
    return f"{'' if beds == 'ALL' else beds + '-bedroom '}{'home' if dwelling == 'ALL' else dwelling.lower()}"


def one_bed(data, beds):
    """File 2's one-bedroom data note (Tenancy Services), carried into every chat answer about 1-bedroom homes."""
    n = data["by_type"].loc[data["by_type"]["beds"] == "1", "data_note"].dropna()
    return [n.iloc[0]] if beds == "1" and len(n) else []


CHECK = {"ok": "Passes sample checks", "verify": "Fails sample checks (few rentals or jumpy price)", "no estimate": "No published figure"}


def area_table(df, home, extras=(), level="SA2"):
    """The facts every chat answer shows (rent for the home asked about, its sample check, crime, schools, GPs, shopping centres),
    plus the extra columns asked about."""
    t = pd.DataFrame({"Area": df["sa2_name"], f"Rent $/wk ({home})": df["rent"]})
    if "basis" in df:  # fallbacks: broader steady rent, not this home
        t = t.rename(columns={f"Rent $/wk ({home})": "Broader rent $/wk"}).assign(**{"Rent covers": df["basis"]})
    else:
        t["Sample check"] = df["check"].map(CHECK)
    if "coverage" in df:  # suburb level: which rows are wider-area estimates, beside the figures
        t.insert(1, "Coverage", np.where(df["coverage"].eq("borrowed"), "Wider-area estimate—covers neighbouring places ("
                                         + df["coverage_source_name"].fillna("") + " SA2)", "Own SA2s"))
    t = t.assign(**{"Source-area bonds (12 months)": df["lodged_bonds_4q"],
                    **({"Est. bonds apportioned (estimate)": df["bonds_apportioned"].round(1)} if "bonds_apportioned" in df else {}),
                       "Crime per 1,000 residents": df["crime_per_1000_residents"].round(0), "Crime rating": df["crime_rating"],
                       "Primary schools in area": df["primary_schools_in_area"], "Secondary schools in area": df["secondary_schools_in_area"],
                       "GP clinics in area": df["gp_clinics_in_area"], "Nearest GP km": df["km_to_nearest_gp_clinic"],
                       "Shopping centres in area": df["shopping_centres_in_area"],
                       "Nearest shopping centre": df["nearest_shopping_centre"] + " (" + df["km_to_nearest_shopping_centre"].map("{:.1f}".format) + " km)",
                       **{label: df[col] for x in extras for label, col in EXTRA_COLS[x].items()}}).reset_index(drop=True)
    if "mosque" in extras:  # METRIC_RULES wording for a zero
        t["Mosque inside area"] = t["Mosque inside area"].map(lambda n: f"No mosque mapped inside this {level}" if n == 0 else f"{n:.0f} mapped")
    return t


def notes(data, extra=(), extras=()):
    return [*extra,
            f"Rent = median weekly rent on new tenancies (MBIE bonds), average of the last 4 quarters ({rent_period(data)}). It is a typical "
            "rent, not what all renters pay and not a listing available at that price. 'Passes sample checks' = 30+ new bonds in 12 months "
            "and a steady price between quarters; it does not make the figure precise."
            + (" At suburb level the 30-bond rule is applied to the MBIE source area's bonds (Source-area bonds); the share apportioned "
               "to the suburb is an estimate, shown but not tested." if unit(data) == "suburb" else ""),
            "Crime = NZ Police recorded victimisations per 1,000 residents, Oct 2025–Sep 2026; busy centres with many visitors look worse. "
            "Hotspots are not rated.",
            "Schools are counted inside the area boundary by year levels served. GPs, shopping centres, parks, playgrounds and "
            "supermarkets come from OpenStreetMap: 0 means none mapped, not none. Distances are straight-line. "
            + ("Areas are LINZ suburbs. Facility counts and distances use the suburb's own LINZ boundary (distances from a point inside "
               "it); census, valuation, crime and rent figures come from the Stats NZ SA2 areas assigned to it, so they approximate the "
               "suburb. Suburb rents are a lodgement-weighted mean of MBIE rent-area medians (MBIE publishes no suburb median)."
               if unit(data) == "suburb" else
               "Areas are Stats NZ SA2 areas, close to but not the same as suburbs."),
            *[EXTRA_NOTES[x] for x in extras if EXTRA_NOTES[x]]]


def extras_for(p):
    """Extra columns for these preferences: asked about (show) plus those of any active filter, in a fixed order."""
    on = set(p.get("show", [])) | {WANTS[k][2] for k in WANTS if p.get(k) and WANTS[k][2]}
    return [x for x in EXTRA_COLS if x in on]


def reply(text, prefs, tables=(), notes_=(), manual=False):
    return dict(text=text, tables=list(tables), notes=list(notes_), prefs=prefs, manual=manual)


def respond(data, question, prefs, history, extract):
    """Answer one message. extract(question, prefs, history) -> Ask (Gemini in the app, a stub in tests).
    prefs carries budget, home, bedrooms, wishes, extra columns, areas and the last intent between messages; the reply holds
    the updated prefs."""
    return answer(data, extract(question, prefs, history), prefs)


def answer(data, ask, prefs):
    p = {**prefs, **ask.model_dump(include={"max_rent", "dwelling", "beds", "include_apt", "near_km", *WANTS}, exclude_none=True)}
    if ask.areas:
        p["areas"] = ask.areas
    if ask.show:
        p["show"] = sorted(set(prefs.get("show", [])) | set(ask.show))
    extras = extras_for(p)
    bad = [m for m, k, ok in (("a weekly budget above $0", "max_rent", lambda v: v > 0), ("a distance above 0 km", "near_km", lambda v: v > 0),
                              ("a Muslim share between 0 and 100%", "min_muslim_pct", lambda v: 0 <= v <= 100))
           if getattr(ask, k) is not None and not ok(getattr(ask, k))]
    if bad:  # never search on an impossible filter; earlier preferences stay as they were
        return reply("Please give " + " and ".join(bad) + ".", prefs)
    if ask.intent == "other":
        return reply("I can only answer from this project's data: rents by area and home type, recorded crime, schools, GPs, shops, "
                     "parks, census communities and mapped mosques and halal food in each Auckland area. Try a budget search (\"3-bed houses under $650 a week\") or ask about an area (\"crime and schools "
                     "in Avondale Central\"). House sale prices exist only Auckland-wide here, never by suburb.", p)
    if ask.intent == "clarify":
        return reply(ask.question or "What weekly rent budget, home type and number of bedrooms should I search for?", p)

    p["intent"] = ask.intent
    dwelling, beds = p.get("dwelling", "ALL"), p.get("beds", "ALL")
    home = home_label(dwelling, beds)
    unset = [label for label, k in (("home type", "dwelling"), ("bedrooms", "beds")) if k not in p]
    assumed = [f"No {' or '.join(unset)} given, so any is included. Say e.g. '3-bed house' to narrow it."] if unset else []

    if ask.intent == "rental_search":
        budget = p.get("max_rent")
        # shortcut: no budget = no cap (rent can't reach $100k/wk), so the answer lists every area that passes the checks, cheapest first
        res = rental_search(data, budget or 100_000, dwelling, beds, p.get("include_apt"))

        def cut(res, keep):  # same search, fewer areas: keep(df) -> bool mask
            res = {**res, **{k: res[k][keep(res[k])] for k in ("areas", "under", "matches", "fallbacks", "shared")}}
            a = res["areas"]
            return {**res, "cheapest_ok": a.loc[a["independent"] & (a["check"] == "ok"), "rent"].min()}
        # Areas named in this message, or kept from a previous budget search in named areas ("and 2 bedrooms?")
        where = ask.areas or (prefs.get("areas", []) if prefs.get("intent") == "rental_search" else [])
        p.pop("areas", None)
        p.update({"areas": where} if where else {})
        hits = {a: area_hits(data, a) for a in where}
        unknown = [a for a, h in hits.items() if not h]
        in_area = sorted({n for h in hits.values() for n in h})
        place = ""
        searched = set(res["areas"]["sa2_name"])  # after the search's own rules (hotspots, apartments), before preferences
        wants = [k for k in WANTS if p.get(k)]
        for k in wants:
            res = cut(res, lambda df: WANTS[k][1](df, p))
        if wants:
            w = [WANTS[k][0](p) for k in wants]
            place += " with " + (", ".join(w[:-1]) + " and " if len(w) > 1 else "") + w[-1]
        if not budget:
            assumed.append("No budget given, so every area that passes the sample checks is listed, cheapest first. "
                           "Add a budget (e.g. '$650 a week') to narrow it.")
        if in_area:  # same search, cut to the named areas
            left_out = sorted(set(in_area) - searched)
            res = cut(res, lambda df: df["sa2_name"].isin(in_area))
            place = " in " + ", ".join(a for a in where if hits[a]) + place
            if left_out:
                assumed.append("Left out by the search rules (crime hotspot, apartment or inner-city area, or not analysis-ready): "
                               + ", ".join(left_out) + ". Ask about the area directly to see its figures.")
        if unknown:
            assumed.append(f"Couldn't match {', '.join(unknown)} to an Auckland area name"
                           + (", so it was left out." if in_area else ", so this searches all of Auckland. Try a suburb name."))
        m, fb = res["matches"], res["fallbacks"]
        fails = (res["under"]["check"] == "verify").sum()
        apt_in = p.get("include_apt", dwelling == "Apartment")  # rental_search's own default
        excluded = ("Crime hotspots are left out" + ("" if apt_in else ", and so are apartment and inner-city areas (ask to include them)")
                    + ". " + (f"{n_none} areas have no published rent for a {home}, so they are not shown." if (n_none := (res["areas"]["check"] == "no estimate").sum()) else ""))
        tables = []
        cap = f" of ${budget:,} a week or less" if budget else ""
        if len(m):
            top = ", ".join(f"{n} (${r:,.0f})" for n, r in zip(m["sa2_name"].head(5), m["rent"].head(5)))
            text = (f"**{len(m)} area{'s' * (len(m) > 1)}**{place} {'have' if len(m) > 1 else 'has'} a typical {home} rent{cap} that "
                    f"passes the sample checks. Cheapest: {top}{', …' if len(m) > 5 else '.'} All of them are in the table below.")
            tables.append((f"{'Budget matches' if budget else 'Areas'}: {home}{place}" + (f", up to ${budget:,}/wk" if budget else ""),
                           area_table(m, home, extras, unit(data))))
        else:
            cheapest = res["cheapest_ok"]
            text = (f"**No area matches.** No area{place} has a {home} rent{cap} that passes the sample checks."
                    + (f" The cheapest figure that passes them is ${cheapest:,.0f} a week; try a higher budget or fewer bedrooms."
                       if pd.notna(cheapest) else " Try fewer conditions, another home type or fewer bedrooms."))
        if fails:
            text += (f" {fails} more areas have a figure{' under budget' if budget else ''} that fails the sample checks, "
                     "so they are not listed as matches.")
        if len(fb):
            tables.append((f"Areas to investigate ({len(fb)}): not matches, broader rent data", area_table(fb, home, extras, unit(data))))
            text += (f" {len(fb)} areas have a broader steady rent{' under budget' if budget else ''}, listed separately: a rent across "
                     f"all sizes cannot show what a {home} costs, so check live listings.")
        sh = res["shared"]
        if len(sh):
            tables.append((f"Wider-area estimates ({len(sh)}): places with no SA2 of their own, not budget matches",
                           area_table(sh, home, extras, unit(data))))
            text += (f" {len(sh)} more places have a figure{' under budget' if budget else ''} that is a wider-area estimate (the whole "
                     "neighbouring SA2's), listed separately.")
        return reply(text, p, tables, notes(data, [*assumed, *one_bed(data, beds), excluded], extras))

    # area_info / compare: one row per area, same rent and sample-check rule as the manual search
    found, missing, split = [], [], []
    for a in p.get("areas", []):
        hits = area_hits(data, a)
        if not hits:
            missing.append(a)
        elif len(hits) > 8:  # up to 8 parts of one suburb are shown; more, and we ask
            return reply(f"\"{a}\" matches {len(hits)} areas ({', '.join(hits[:8])}{', …' if len(hits) > 8 else ''}). Which one do you mean?", p)
        else:
            split += [a] if len(hits) > 1 else []
            found += [h for h in hits if h not in found]
    if not found:
        return reply(("I couldn't find " + ", ".join(f'"{a}"' for a in missing) + " among Auckland's areas. Check the spelling or try a "
                      "nearby suburb name.") if missing else "Which area should I look up?", p)
    sa2 = data["sa2"]
    rows = with_home_rent(sa2[sa2["sa2_name"].isin(found)], data, dwelling, beds).set_index("sa2_name").loc[found].reset_index()
    t = area_table(rows, home, extras, unit(data))
    extra = list(assumed)
    if p.get("max_rent"):
        b = p["max_rent"]
        t.insert(3, f"Within ${b:,}/wk?", ["No published figure" if c == "no estimate" else "No" if r > b else
                                          "Yes, passes sample checks" if c == "ok" else "Under budget, but fails sample checks"
                                          for r, c in zip(rows["rent"], rows["check"])])
    if split:
        extra.append(", ".join(split) + f" matches more than one {unit(data)}, so each is shown.")
    if missing:
        extra.append("Not found: " + ", ".join(missing) + ".")
    if (~rows["analysis_ready"]).any():
        extra.append("Not analysis-ready (too few residents or rentals): " + ", ".join(rows.loc[~rows["analysis_ready"], "sa2_name"]) + ".")
    for _, x in rows.iterrows():  # exceptional-place and shared-area warnings, named per row
        extra += [f"{x['sa2_name']}: {x[c]}" for c in ("special_note", "coverage_note") if x.get(c)]
    if unit(data) == "suburb" and rows["flag_shared_rent_area"].eq(True).any():
        extra.append("Rent series shared with another suburb (same MBIE rent area): "
                     + ", ".join(rows.loc[rows["flag_shared_rent_area"].eq(True), "sa2_name"]) + ".")
    elif unit(data) == "SA2" and rows["flag_borrowed_rent"].eq(True).any():
        extra.append("Shares rent figures with a neighbouring area: " + ", ".join(rows.loc[rows["flag_borrowed_rent"].eq(True), "sa2_name"]) + ".")
    extra += one_bed(data, beds)
    text = ((f"Comparing {len(found)} areas" if len(found) > 1 else f"**{found[0]}**") + f": rent for a {home}, crime, schools, GPs and "
            "shopping centres" + "".join(f", {EXTRA_NAMES[x]}" for x in extras) + ".")
    return reply(text, p, [(f"{home.capitalize()} rent and area facts", t)], notes(data, extra, extras))


def stub(*answers):
    """Test extractor that replays fixed Ask results instead of calling Gemini."""
    it = iter(answers)
    return lambda question, prefs, history: next(it)


if __name__ == "__main__":
    from search import load_data
    # Suburb level (the default): suburb names first, an SA2 name gives its suburb; chat = manual search
    s = load_data()
    assert area_hits(s, "Ponsonby East") == ["Ponsonby"] and area_hits(s, "mt roskill") == ["Mount Roskill"]
    assert area_hits(s, "Ponsonby") == ["Ponsonby"] and area_hits(s, "Papatoetoe") == ["Papatoetoe"]
    rs = respond(s, "x", {}, [], stub(Ask(intent="rental_search", max_rent=700, dwelling="House", beds="3")))
    assert rs["tables"][0][1]["Area"].tolist() == rental_search(s, 700, "House", "3")["matches"]["sa2_name"].tolist()
    assert any("LINZ suburbs" in n for n in rs["notes"])
    assert rs["tables"][-1][0].startswith("Wider-area estimates") and "Coverage" in rs["tables"][0][1]
    assert set(rs["tables"][-1][1]["Area"]) == set(rental_search(s, 700, "House", "3")["shared"]["sa2_name"])
    wk = respond(s, "x", {}, [], stub(Ask(intent="area_info", areas=["Waiake"])))
    assert any("Wider-area estimate" in n and "Torbay" in n for n in wk["notes"])
    assert any("6 census residents" in n for n in respond(s, "x", {}, [], stub(Ask(intent="area_info", areas=["Huntington Park"])))["notes"])
    assert any("one-bedroom" in n for n in respond(s, "x", {}, [], stub(Ask(intent="rental_search", max_rent=500, beds="1")))["notes"])
    for bad in (dict(max_rent=-5), dict(max_rent=0), dict(near_km=-1), dict(min_muslim_pct=150)):
        assert respond(s, "x", {"max_rent": 600}, [], stub(Ask(intent="rental_search", **bad)))["prefs"] == {"max_rent": 600}
    import httpx2  # google-genai's default backend
    calls = []

    def flaky(*a):
        calls.append(1)
        raise httpx2.ReadTimeout("timed out")
    try:
        with_retries(flaky, sleep=lambda s: None)
    except httpx2.ReadTimeout:
        assert len(calls) == RETRIES + 1  # bounded: tried, retried twice, then the app shows the manual fallback
    assert over_limit(SESSION_LIMIT, 0) and over_limit(0, DAILY_LIMIT) and over_limit(0, 0) is None
    ai = respond(s, "x", {}, [], stub(Ask(intent="area_info", areas=["Mt Roskill"], show=["mosque"])))
    assert ai["tables"][0][1]["Area"].tolist() == ["Mount Roskill"] and "this SA2" not in ai["tables"][0][1].to_string()
    d = load_data("sa2")
    # Same filters as the manual reference search ($600, 3-bed house) -> same areas
    r = respond(d, "3 bed house under 600", {}, [], stub(Ask(intent="rental_search", max_rent=600, dwelling="House", beds="3")))
    ref = rental_search(d, 600, "House", "3")
    assert "No area matches" in r["text"] and len(r["tables"]) == 1
    assert r["tables"][0][1]["Area"].tolist() == ref["fallbacks"]["sa2_name"].tolist()
    # Follow-up keeps budget and home, changes bedrooms
    r2 = respond(d, "what about 2 bedrooms", r["prefs"], [], stub(Ask(intent="rental_search", beds="2")))
    assert r2["prefs"] == {"max_rent": 600, "dwelling": "House", "beds": "2", "intent": "rental_search"}
    assert r2["tables"][0][1]["Area"].tolist() == rental_search(d, 600, "House", "2")["matches"]["sa2_name"].tolist()
    # Budget missing -> asks; split and ambiguous areas; no mosque columns anywhere
    nb = respond(d, "cheap houses", {}, [], stub(Ask(intent="rental_search", dwelling="House")))  # no budget: list, cheapest first
    assert nb["tables"][0][1]["Area"].tolist() == rental_search(d, 100_000, "House", "ALL")["matches"]["sa2_name"].tolist() and any("No budget given" in n for n in nb["notes"])
    sc = respond(d, "x", {}, [], stub(Ask(intent="rental_search", max_rent=700, dwelling="House", beds="3", low_crime=True, school=True)))
    t = sc["tables"][0][1]
    assert len(t) and t["Crime rating"].eq("Low").all() and t["Primary schools in area"].gt(0).all() and "low recorded crime and a primary school" in sc["text"]
    a = respond(d, "Ponsonby", {}, [], stub(Ask(intent="area_info", areas=["ponsonby"])))
    assert a["tables"][0][1]["Area"].tolist() == ["Ponsonby East", "Ponsonby West"]
    assert "Which one" in respond(d, "Mt Roskill", {}, [], stub(Ask(intent="area_info", areas=["Mt Roskill"])))["text"]
    assert find_areas(sorted(d["sa2"]["sa2_name"]), "avondale central") == ["Avondale Central (Auckland)"]
    # Base columns always; extras only when asked about or filtered on
    assert not any("osque" in c or "Muslim" in c for x in (r, r2, a) for _, df in x["tables"] for c in df.columns)
    assert {"GP clinics in area", "Nearest shopping centre", "Crime rating"} <= set(a["tables"][0][1].columns)
    # Budget search inside named areas: cut to those SA2s, kept for follow-ups; unknown names said out loud
    g = respond(d, "x", {}, [], stub(Ask(intent="rental_search", max_rent=900, dwelling="House", beds="3", areas=["Grey Lynn"])))
    gl = rental_search(d, 900, "House", "3")["matches"]
    assert g["tables"][0][1]["Area"].tolist() == gl[gl["sa2_name"].str.startswith("Grey Lynn")]["sa2_name"].tolist() and " in Grey Lynn" in g["text"]
    assert respond(d, "x", g["prefs"], [], stub(Ask(intent="rental_search", beds="2")))["prefs"]["areas"] == ["Grey Lynn"]
    u = respond(d, "x", {}, [], stub(Ask(intent="rental_search", max_rent=500, dwelling="Apartment", areas=["city centre"])))
    assert any("searches all of Auckland" in n for n in u["notes"])
    # "2 bedroom house/unit, more than 5% Muslim, near a mosque and halal shops": same areas as filtering the manual search
    mq = respond(d, "x", {}, [], stub(Ask(intent="rental_search", dwelling="ALL", beds="2", min_muslim_pct=5, near_mosque=True, near_halal=True)))
    ref = rental_search(d, 100_000, "ALL", "2")["matches"]
    ref = ref[ref["pct_muslim"].gt(5) & ref["km_to_nearest_mosque"].le(3) & (ref["halal_places_in_area"].gt(0) | ref["halal_butchers_in_area"].gt(0)
              | ref["km_to_nearest_halal_butcher"].le(3))]
    t = mq["tables"][0][1]
    assert len(ref) and t["Area"].tolist() == ref["sa2_name"].tolist() and t["Muslim residents % (2023 Census)"].gt(5).all()
    assert {"Nearest mapped mosque", "Halal butchers mapped inside"} <= set(t.columns) and "Parks in area" not in t
    assert any("33 mapped" in n for n in mq["notes"]) and any("Census shares" in n for n in mq["notes"])
    # Follow-up keeps the wishes; 'show' adds a column without filtering
    sh = respond(d, "x", mq["prefs"], [], stub(Ask(intent="rental_search", show=["park"])))
    assert sh["tables"][0][1]["Area"].tolist() == t["Area"].tolist() and "Parks in area" in sh["tables"][0][1]
    print("chat.py self-check passed")
