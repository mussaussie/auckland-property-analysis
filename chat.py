"""Ask Auckland: Gemini reads the question, search.py answers it.

The model only turns a message into filters (intent, budget, home type, bedrooms, area names). Every figure, table and
caveat in the reply is built here from data/clean with the same functions the manual pages use (search.py), so a chat
search and a manual search with the same filters give the same areas and rents.
Self-check (no API call): python chat.py
"""
import json
import re
import unicodedata
from typing import Literal, Optional

import pandas as pd
from pydantic import BaseModel, Field

from search import rent_period, rental_search, with_home_rent

MODEL = "gemini-3.5-flash-lite"  # free tier about 500 requests/day (Nov 2026); Flash is about 20/day. One request per question.


class Ask(BaseModel):
    intent: Literal["rental_search", "area_info", "compare", "mosque", "clarify", "other"]
    max_rent: Optional[int] = Field(None, description="Weekly rent budget in NZ dollars, only if stated in this message")
    dwelling: Optional[Literal["House", "Apartment", "Flat", "ALL"]] = Field(None, description="Home type, only if stated in this message")
    beds: Optional[Literal["1", "2", "3", "4", "5+", "ALL"]] = Field(None, description="Bedrooms, only if stated in this message")
    include_apt: Optional[bool] = Field(None, description="True only if the user asks to include apartments or the city centre")
    low_crime: Optional[bool] = Field(None, description="True if the user wants safe / low-crime areas; false if they drop that wish")
    school: Optional[bool] = Field(None, description="True if the user wants a (primary) school in the area; false if they drop it")
    park: Optional[bool] = Field(None, description="True if the user wants parks or green space in the area; false if they drop it")
    areas: list[str] = Field(default_factory=list, description="Suburb or area names as the user wrote them in this message")
    question: Optional[str] = Field(None, description="When intent is clarify: one short question for the user")


SYSTEM = """You turn messages about renting in Auckland, New Zealand into search filters for a dashboard.
Never answer the question yourself and never give figures: return only JSON that matches the schema.
intent:
- rental_search: any request for a list of suburbs or areas to rent in: by budget, home type, bedrooms, safety (low_crime),
  schools (school), parks (park) or a place. A budget is optional ("safe suburbs with schools for a 3 bed house").
- area_info: facts about one named area (rent, crime, schools, parks, whether it fits a budget).
- compare: two or more named areas side by side.
- mosque: mosques, prayer places, halal food or religious communities. Still fill max_rent, dwelling, beds and areas if the
  message gives them ("3 bed house under $700 near a mosque in Mt Roskill").
- clarify: too vague to search, e.g. "where should I live?" with no budget or area; put one short question in `question`.
- other: anything else (house sale prices, forecasts, investment advice, other cities, small talk).
Filters: max_rent is NZ$ per week (monthly x 12 / 52, fortnightly / 2). dwelling: House, Apartment, Flat (flat or unit) or ALL (any home).
beds: "1" to "4", "5+" or "ALL"; a studio is "1".
areas: suburb names in full, with nicknames expanded (Pt Chev -> Point Chevalier, Grey Lynn stays Grey Lynn). Fill areas for any
intent when the message names a place, including a budget search limited to a place.

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


# Optional wishes: (wording, filter on the search's rows). Low = lowest third of comparable areas by recorded crime per resident.
WANTS = {"low_crime": ("low recorded crime", lambda df: df["crime_rating"].eq("Low")),
         "school": ("a primary school inside", lambda df: df["primary_schools_in_area"].gt(0)),
         "park": ("a park mapped inside", lambda df: df["parks_in_area"].gt(0))}


def home_label(dwelling, beds):
    return f"{'' if beds == 'ALL' else beds + '-bedroom '}{'home' if dwelling == 'ALL' else dwelling.lower()}"


CHECK = {"ok": "Passes sample checks", "verify": "Fails sample checks (few rentals or jumpy price)", "no estimate": "No published figure"}


def area_table(df, home):
    """The facts every chat answer shows: rent for the home asked about, its sample check, crime, schools and parks (no mosques)."""
    t = pd.DataFrame({"Area": df["sa2_name"], f"Rent $/wk ({home})": df["rent"]})
    if "basis" in df:  # fallbacks: broader steady rent, not this home
        t = t.rename(columns={f"Rent $/wk ({home})": "Broader rent $/wk"}).assign(**{"Rent covers": df["basis"]})
    else:
        t["Sample check"] = df["check"].map(CHECK)
    return t.assign(**{"New rentals (12 months)": df["lodged_bonds_4q"],
                       "Crime per 1,000 residents": df["crime_per_1000_residents"].round(0), "Crime rating": df["crime_rating"],
                       "Primary schools in area": df["primary_schools_in_area"], "Secondary schools in area": df["secondary_schools_in_area"],
                       "Parks in area": df["parks_in_area"]}).reset_index(drop=True)


def notes(data, extra=()):
    return [*extra,
            f"Rent = median weekly rent on new tenancies (MBIE bonds), average of the last 4 quarters ({rent_period(data)}). It is not what all "
            "renters pay. 'Passes sample checks' = 30+ new rentals in 12 months and a steady price between quarters; it does not make the "
            "figure precise or mean a home is available at that price.",
            "Crime = NZ Police recorded victimisations per 1,000 residents, Oct 2025–Sep 2026; busy centres with many visitors look worse. "
            "Hotspots are not rated.",
            "Schools are counted inside the area boundary by year levels served. Parks come from OpenStreetMap: 0 means none mapped, "
            "not none. Areas are Stats NZ SA2 areas, close to but not the same as suburbs."]


def reply(text, prefs, tables=(), notes_=(), manual=False):
    return dict(text=text, tables=list(tables), notes=list(notes_), prefs=prefs, manual=manual)


MOSQUE_NOTE = ("Ask Auckland leaves mosque information out. To see mapped mosques, switch on Show nearby mosques in the sidebar and "
               "use Find a rental under my budget or Family screen. The mapped list is partial and distances are straight-line. Census "
               "shares show where people live, not where mosques or halal shops are.")


def respond(data, question, prefs, history, extract):
    """Answer one message. extract(question, prefs, history) -> Ask (Gemini in the app, a stub in tests).
    prefs carries budget, home, bedrooms, areas and the last intent between messages; the reply holds the updated prefs.
    A mosque question that also gives a budget, home or area ("3 bed under $700 near a mosque") is searched as usual,
    with the mosque note on top; mosque details themselves stay in the manual search."""
    ask = extract(question, prefs, history)
    mixed = ask.intent == "mosque" and bool(ask.max_rent or ask.areas or ask.dwelling or ask.beds)
    if mixed:
        ask = ask.model_copy(update={"intent": "rental_search" if ask.max_rent or not ask.areas else "area_info"})
    r = answer(data, ask, prefs)
    if mixed:
        r["notes"].insert(0, MOSQUE_NOTE)
        r["manual"] = True
    return r


def answer(data, ask, prefs):
    p = {**prefs, **ask.model_dump(include={"max_rent", "dwelling", "beds", "include_apt", *WANTS}, exclude_none=True)}
    if ask.areas:
        p["areas"] = ask.areas
    if ask.intent == "mosque":
        return reply(MOSQUE_NOTE.replace("Show nearby mosques", "**Show nearby mosques**"), p, manual=True)
    if ask.intent == "other":
        return reply("I can only answer from this project's data: rents by area and home type, recorded crime, schools and parks in each "
                     "Auckland area. Try a budget search (\"3-bed houses under $650 a week\") or ask about an area (\"crime and schools "
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
            res = {**res, **{k: res[k][keep(res[k])] for k in ("areas", "under", "matches", "fallbacks")}}
            return {**res, "cheapest_ok": res["areas"].loc[res["areas"]["check"] == "ok", "rent"].min()}
        # Areas named in this message, or kept from a previous budget search in named areas ("and 2 bedrooms?")
        where = ask.areas or (prefs.get("areas", []) if prefs.get("intent") == "rental_search" else [])
        p.pop("areas", None)
        p.update({"areas": where} if where else {})
        names = sorted(data["sa2"]["sa2_name"])
        hits = {a: find_areas(names, a) for a in where}
        unknown = [a for a, h in hits.items() if not h]
        in_area = sorted({n for h in hits.values() for n in h})
        place = ""
        searched = set(res["areas"]["sa2_name"])  # after the search's own rules (hotspots, apartments), before preferences
        wants = [k for k in WANTS if p.get(k)]
        for k in wants:
            res = cut(res, WANTS[k][1])
        if wants:
            w = [WANTS[k][0] for k in wants]
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
                           area_table(m, home)))
        else:
            cheapest = res["cheapest_ok"]
            text = (f"**No area matches.** No area{place} has a {home} rent{cap} that passes the sample checks."
                    + (f" The cheapest figure that passes them is ${cheapest:,.0f} a week; try a higher budget or fewer bedrooms."
                       if pd.notna(cheapest) else " Try fewer conditions, another home type or fewer bedrooms."))
        if fails:
            text += (f" {fails} more areas have a figure{' under budget' if budget else ''} that fails the sample checks, "
                     "so they are not listed as matches.")
        if len(fb):
            tables.append((f"Areas to investigate ({len(fb)}): not matches, broader rent data", area_table(fb, home)))
            text += (f" {len(fb)} areas have a broader steady rent{' under budget' if budget else ''}, listed separately: a rent across "
                     f"all sizes cannot show what a {home} costs, so check live listings.")
        return reply(text, p, tables, notes(data, [*assumed, excluded]))

    # area_info / compare: one row per area, same rent and sample-check rule as the manual search
    names = sorted(data["sa2"]["sa2_name"])
    found, missing, split = [], [], []
    for a in p.get("areas", []):
        hits = find_areas(names, a)
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
    t = area_table(rows, home)
    extra = list(assumed)
    if p.get("max_rent"):
        b = p["max_rent"]
        t.insert(3, f"Within ${b:,}/wk?", ["No published figure" if c == "no estimate" else "No" if r > b else
                                          "Yes, passes sample checks" if c == "ok" else "Under budget, but fails sample checks"
                                          for r, c in zip(rows["rent"], rows["check"])])
    if split:
        extra.append(", ".join(split) + " covers more than one SA2 area, so each part is shown.")
    if missing:
        extra.append("Not found: " + ", ".join(missing) + ".")
    if (~rows["analysis_ready"]).any():
        extra.append("Not analysis-ready (too few residents or rentals): " + ", ".join(rows.loc[~rows["analysis_ready"], "sa2_name"]) + ".")
    if rows["flag_borrowed_rent"].eq(True).any():
        extra.append("Shares rent figures with a neighbouring area: " + ", ".join(rows.loc[rows["flag_borrowed_rent"].eq(True), "sa2_name"]) + ".")
    text = (f"Comparing {len(found)} areas" if len(found) > 1 else f"**{found[0]}**") + f": rent for a {home}, crime, schools and parks."
    return reply(text, p, [(f"{home.capitalize()} rent and area facts", t)], notes(data, extra))


def stub(*answers):
    """Test extractor that replays fixed Ask results instead of calling Gemini."""
    it = iter(answers)
    return lambda question, prefs, history: next(it)


if __name__ == "__main__":
    from search import load_data
    d = load_data()
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
    assert not any("osque" in c for x in (r, r2, a) for _, df in x["tables"] for c in df.columns)
    # Budget search inside named areas: cut to those SA2s, kept for follow-ups; unknown names said out loud
    g = respond(d, "x", {}, [], stub(Ask(intent="rental_search", max_rent=900, dwelling="House", beds="3", areas=["Grey Lynn"])))
    gl = rental_search(d, 900, "House", "3")["matches"]
    assert g["tables"][0][1]["Area"].tolist() == gl[gl["sa2_name"].str.startswith("Grey Lynn")]["sa2_name"].tolist() and " in Grey Lynn" in g["text"]
    assert respond(d, "x", g["prefs"], [], stub(Ask(intent="rental_search", beds="2")))["prefs"]["areas"] == ["Grey Lynn"]
    u = respond(d, "x", {}, [], stub(Ask(intent="rental_search", max_rent=500, dwelling="Apartment", areas=["city centre"])))
    assert any("searches all of Auckland" in n for n in u["notes"])
    # Mosque question with a budget: searched as usual, mosque note first, no mosque columns
    mq = respond(d, "x", {}, [], stub(Ask(intent="mosque", max_rent=700, dwelling="House", beds="3")))
    assert mq["notes"][0] == MOSQUE_NOTE and mq["tables"][0][1]["Area"].tolist() == rental_search(d, 700, "House", "3")["matches"]["sa2_name"].tolist()
    assert not respond(d, "x", {}, [], stub(Ask(intent="mosque")))["tables"]
    print("chat.py self-check passed")
