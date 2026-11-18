"""Auckland Property Insights: suburb property dashboard.

Reads only data/clean/, the SA2 geojson and METRIC_RULES.md (Methodology and Glossary are rendered from it).
Run: streamlit run app.py      Previous design: app_v1_2026-11-18.py
"""
import html
import json

import geopandas as gpd
import markdown
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

CLEAN = "data/clean"
st.set_page_config(page_title="Auckland Property Insights", page_icon="🏠", layout="wide")

# ---------- design tokens ----------
INK, MUTED, LINE = "#0f172a", "#64748b", "#e2e8f0"
GREEN, AMBER, BLUE, RED = "#16a34a", "#d97706", "#2563eb", "#dc2626"   # KPI borders: count, rent/price, volume, risk
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]  # dataviz categorical order
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIV = ["#184f95", "#5598e7", "#f0efec", "#ec8a89", "#b8302f"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], p, label, li, span, div, h1, h2, h3, h4, button, input { font-family: 'Inter', system-ui, sans-serif !important; }
.stApp { background: #f8fafc; }
.block-container { padding-top: 1.6rem; max-width: 1360px; }
h1, h2, h3 { color: #0f172a; letter-spacing: -0.015em; }
section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e2e8f0; }
.card { background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); border: 1px solid #eef2f7; padding: 18px 20px; margin-bottom: 14px; }
.card h4 { margin: 0 0 6px; font-size: 1rem; color: #0f172a; }
.card p, .card li { font-size: .86rem; color: #334155; line-height: 1.5; }
.kicker { font-size: .72rem; letter-spacing: .14em; font-weight: 700; color: #2563eb; text-transform: uppercase; }
.hero h1 { font-size: 1.9rem; font-weight: 800; margin: 6px 0 4px; }
.hero p { color: #64748b; margin: 0; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(165px, 1fr)); gap: 14px; margin: 4px 0 18px; }
.kpi { background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); border-top: 4px solid var(--c); padding: 14px 16px; }
.kpi .l { font-size: .72rem; color: #64748b; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
.kpi .v { font-size: 1.55rem; font-weight: 700; color: #0f172a; margin-top: 4px; }
.kpi .c { font-size: .74rem; color: #64748b; margin-top: 4px; line-height: 1.35; }
.badge { display: inline-block; font-size: .72rem; font-weight: 600; padding: 2px 10px; border-radius: 999px; margin: 0 6px 6px 0; }
.badge.ok { background: #dcfce7; color: #166534; } .badge.warn { background: #fef3c7; color: #92400e; }
.badge.bad { background: #fee2e2; color: #991b1b; } .badge.info { background: #dbeafe; color: #1e40af; }
.pill { display: inline-block; background: #f1f5f9; border-radius: 8px; padding: 4px 9px; margin: 6px 6px 0 0; font-size: .78rem; color: #475569; }
.pill b { color: #0f172a; }
.snap .name { font-weight: 700; font-size: 1rem; color: #0f172a; } .snap .type { font-size: .76rem; color: #64748b; margin-bottom: 8px; }
.caveat { font-size: .78rem; color: #64748b; margin: 2px 0 16px; line-height: 1.45; }
.brand .t { font-weight: 800; font-size: 1.08rem; color: #0f172a; } .brand .s { font-size: .8rem; color: #64748b; margin-bottom: 10px; }
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"] { background: #fff; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.04); padding: 6px; }
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
</style>
""", unsafe_allow_html=True)


# ---------- small helpers ----------
def esc(x):
    return html.escape(str(x))


def money(v):
    return "—" if pd.isna(v) else f"${v:,.0f}"


def num(v, f="{:.1f}", suffix=""):
    return "—" if pd.isna(v) else f.format(v) + suffix


def kpis(items):
    """items: (label, value, caption, colour)."""
    st.markdown('<div class="kpis">' + "".join(
        f'<div class="kpi" style="--c:{c}"><div class="l">{esc(l)}</div><div class="v">{esc(v)}</div><div class="c">{esc(cap)}</div></div>'
        for l, v, cap, c in items) + "</div>", unsafe_allow_html=True)


def card(inner_html):
    st.markdown(f'<div class="card">{inner_html}</div>', unsafe_allow_html=True)


def md_card(title, body):
    card(markdown.markdown(f"#### {title}\n\n{body}"))


def caveat(text):
    st.markdown(f'<div class="caveat">{esc(text)}</div>', unsafe_allow_html=True)


def badge_html(items):
    return "".join(f'<span class="badge {k}">{esc(t)}</span>' for t, k in items)


def style(fig, height=360, title=None):
    fig.update_layout(height=height, title=title, margin=dict(l=10, r=10, t=44 if title else 16, b=10),
                      paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", hovermode="closest",
                      font=dict(family="Inter, system-ui, sans-serif", color=INK, size=12), title_font=dict(size=15),
                      legend=dict(orientation="h", y=-0.18, x=0))
    fig.update_xaxes(showgrid=False, linecolor=LINE)
    fig.update_yaxes(gridcolor="#f1f5f9", zeroline=False)
    return fig


# ---------- data ----------
@st.cache_data
def load():
    sa2 = pd.read_csv(f"{CLEAN}/master_flagged.csv")
    for f in ["rent_metrics_by_sa2", "area_profiles_by_sa2", "risk_value_screen", "rent_market_by_sa2", "rent_premium_by_sa2",
              "rent_forecast_by_sa2"]:
        d = pd.read_csv(f"{CLEAN}/{f}.csv").rename(columns={"flag_thin_sample": "forecast_thin_sample"})  # only the forecast file has it
        new = [c for c in d.columns if c not in sa2.columns]
        sa2 = sa2.merge(d[["sa2_code"] + new], on="sa2_code", how="left")
    # Police crime groups: person = assault, harm/endanger, sexual, robbery; property = burglary, theft (the six sum to crime_total)
    sa2["crime_person"] = sa2[["crime_assault", "crime_harm_or_endanger_persons", "crime_sexual_offences", "crime_robbery"]].sum(axis=1, min_count=1)
    sa2["crime_property"] = sa2[["crime_burglary", "crime_theft"]].sum(axis=1, min_count=1)
    comparable = sa2["analysis_ready"] & ~sa2["flag_crime_hotspot"]
    lo, hi = sa2.loc[comparable, "crime_per_1000_residents"].quantile([1 / 3, 2 / 3])
    sa2["crime_rating"] = np.select([sa2["flag_crime_hotspot"], sa2["crime_per_1000_residents"] <= lo, sa2["crime_per_1000_residents"] <= hi,
                                     sa2["crime_per_1000_residents"] > hi], ["Hotspot", "Low", "Moderate", "High"], default="—")
    sa2.loc[~sa2["analysis_ready"], "crime_rating"] = "—"
    sa2["return_score"] = (sa2["value_score"] + sa2["growth_score"]) / 2
    sa2["risk_level"] = 100 - sa2["risk_score"]          # risk_score: 100 = lowest risk
    return dict(
        sa2=sa2,
        rent_m=pd.read_csv(f"{CLEAN}/auckland_rent_monthly.csv", parse_dates=["month"]),
        sales=pd.read_csv(f"{CLEAN}/auckland_sales_quarterly.csv", parse_dates=["quarter_end"]),
        rent_ts=pd.read_csv(f"{CLEAN}/rent_timeseries_by_sa2.csv", parse_dates=["quarter"]),
        by_type=pd.read_csv(f"{CLEAN}/rent_by_type_sa2.csv", dtype={"beds": str}),
    )


@st.cache_data
def geo():
    g = gpd.read_file("data/boundaries/auckland_sa2_2023.geojson")[["SA22023_V1_00", "geometry"]]
    g["sa2_code"] = g["SA22023_V1_00"].astype(int)
    g["geometry"] = g.geometry.simplify(0.0004, preserve_topology=True)  # ~40 m; keeps the page light
    return json.loads(g[["sa2_code", "geometry"]].to_json())


@st.cache_data
def rules():
    """METRIC_RULES.md split into {heading: body} for the Methodology and Glossary views."""
    out, cur = {}, None
    for line in open("METRIC_RULES.md", encoding="utf-8").read().splitlines():
        if line.startswith("## ") or line.startswith("### "):
            cur = line.lstrip("#").strip()
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


D = load()
S = D["sa2"]
READY = S[S["analysis_ready"]]
RANKED = S[S["ranked"] == True]  # noqa: E712 (object column after merge)
BY_NAME = S.set_index("sa2_name")
on = lambda r, k: r.get(k) == True  # noqa: E731,E712 (blank flags are NaN, which is truthy)


def badges(r):
    out = []
    rating = r.get("crime_rating")
    if rating in ("Low", "Moderate", "High"):
        out.append((f"Crime: {rating}", {"Low": "ok", "Moderate": "warn", "High": "bad"}[rating]))
    if on(r, "flag_crime_hotspot"): out.append(("Crime hotspot: rate not comparable", "bad"))
    if on(r, "flag_borrowed_rent"): out.append(("Shares rent figures with a neighbour", "warn"))
    if on(r, "flag_verify_3bed_house"): out.append(("3-bed rent: verify", "warn"))
    if on(r, "is_new_development"): out.append(("New development: rent history from 2018 parent area", "info"))
    if on(r, "flag_rapid_growth"): out.append(("Rapid growth", "info"))
    if not on(r, "analysis_ready"): out.append(("Not analysis-ready", "bad"))
    if pd.notna(r.get("rank_Balanced")): out.append((f"Screen rank {int(r['rank_Balanced'])} of {len(RANKED)}", "info"))
    return out


def pct_rank(col, v):
    """Share of analysis-ready areas with a lower value (0-100)."""
    s = READY[col].dropna()
    return None if pd.isna(v) or s.empty else round(100 * (s < v).mean())


# ---------- sidebar ----------
VIEWS = ["Overview", "Explore suburb", "Compare suburbs", "Opportunity finder", "Family screen", "Map lab", "Methodology", "Glossary"]
NAMES = sorted(S["sa2_name"])
# The spec's defaults are suburb names; SA2s split them, so the nearest SA2 is used (CBD: Queen Street)
DEFAULT_SUBURB = "Queen Street"
DEFAULT_COMPARE = ["Queen Street", "Albany Central", "Mount Eden North", "Manurewa Central"]
with st.sidebar:
    st.markdown('<div class="brand"><div class="t">Auckland Property Insights</div><div class="s">Suburb Property Dashboard</div></div>',
                unsafe_allow_html=True)
    view = st.radio("View", VIEWS, label_visibility="collapsed")
    st.divider()
    suburb = st.selectbox("Suburb", NAMES, index=NAMES.index(DEFAULT_SUBURB))
    compare = st.multiselect("Compare suburbs", NAMES, default=DEFAULT_COMPARE, max_selections=8)
    st.caption("Suburbs are Stats NZ SA2 areas: names are close to suburb names, boundaries differ. "
               "Sources: Stats NZ 2023 Census, MBIE bonds, Auckland Council valuations, NZ Police, HUD, MoE, Auckland Transport, OpenStreetMap.")
R = BY_NAME.loc[suburb]


# ---------- shared charts ----------
def risk_return(highlight_codes, label="Highlighted"):
    d = RANKED.dropna(subset=["risk_level", "return_score"]).copy()
    d["group"] = np.where(d["sa2_code"].isin(highlight_codes), label, "Other screened areas")
    fig = px.scatter(d, x="risk_level", y="return_score", size="population_2023", color="group", size_max=20,
                     color_discrete_map={"Other screened areas": "#9ec5f4", label: SERIES[1]},
                     category_orders={"group": ["Other screened areas", label]}, hover_name="sa2_name",
                     hover_data={"group": False, "population_2023": False, "risk_level": ":.0f", "return_score": ":.0f",
                                 "gross_yield_pct": ":.2f", "rent_cagr_10y_pct": ":.1f", "crime_per_1000_residents": ":.0f"},
                     labels={"risk_level": "Risk percentile (higher = riskier)", "return_score": "Return percentile (yield + growth)",
                             "gross_yield_pct": "Gross yield %", "rent_cagr_10y_pct": "Rent growth 10y %/yr",
                             "crime_per_1000_residents": "Crime /1,000"})
    fig.update_traces(marker=dict(line=dict(width=1, color="#ffffff")))
    fig.add_hline(y=50, line_dash="dot", line_color="#94a3b8")
    fig.add_vline(x=50, line_dash="dot", line_color="#94a3b8")
    for x, y, t in [(3, 98, "Higher return · lower risk"), (97, 98, "Higher return · higher risk"),
                    (3, 2, "Lower return · lower risk"), (97, 2, "Lower return · higher risk")]:
        fig.add_annotation(x=x, y=y, text=t, showarrow=False, font=dict(size=11, color=MUTED), xanchor="left" if x < 50 else "right")
    fig.update_xaxes(range=[0, 100]); fig.update_yaxes(range=[0, 100])
    return style(fig, 460, "Risk vs return, File 4 screen")


def choropleth(df, col, label, scale, fmt, height=600):
    d = df[["sa2_code", "sa2_name", col]].dropna()
    if scale == "div":
        lim = d[col].abs().quantile(0.95)
        kw = dict(color_continuous_scale=DIV, range_color=(-lim, lim), color_continuous_midpoint=0)
    else:
        kw = dict(color_continuous_scale=SEQ, range_color=(d[col].quantile(0.02), d[col].quantile(0.98)))  # outliers don't flatten the scale
    fig = px.choropleth_mapbox(
        d, geojson=geo(), locations="sa2_code", featureidkey="properties.sa2_code", color=col,
        hover_name="sa2_name", hover_data={"sa2_code": False, col: fmt}, labels={col: label},
        mapbox_style="open-street-map", center=dict(lat=-36.9, lon=174.78), zoom=9, opacity=0.62, **kw)
    fig.update_traces(marker_line_width=0.4, marker_line_color="#ffffff")
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="#ffffff",
                      coloraxis_colorbar=dict(title="", thickness=10, len=0.6), font=dict(family="Inter, system-ui, sans-serif", color=INK))
    return fig


def shortlist_table(df, n=15):
    t = df.head(n)[["sa2_name", "area_type", "median_rent_weekly", "median_cv_2024", "gross_yield_pct", "rent_cagr_10y_pct",
                    "cooling_pa", "crime_per_1000_residents", "rank_Balanced"]]
    st.dataframe(t.rename(columns={
        "sa2_name": "Area", "area_type": "Area type", "median_rent_weekly": "Rent $/wk", "median_cv_2024": "CV 2024",
        "gross_yield_pct": "Gross yield %", "rent_cagr_10y_pct": "Rent growth 10y %/yr", "cooling_pa": "Rent trend 2y %/yr",
        "crime_per_1000_residents": "Crime /1,000", "rank_Balanced": "Screen rank"}),
        hide_index=True, use_container_width=True, column_config={
            "Rent $/wk": st.column_config.NumberColumn(format="$%.0f"), "CV 2024": st.column_config.NumberColumn(format="$%d"),
            "Gross yield %": st.column_config.NumberColumn(format="%.2f"), "Rent growth 10y %/yr": st.column_config.NumberColumn(format="%.1f"),
            "Rent trend 2y %/yr": st.column_config.NumberColumn(format="%.1f"), "Crime /1,000": st.column_config.NumberColumn(format="%.0f"),
            "Screen rank": st.column_config.NumberColumn(format="%d")})


def snapshot_cards(df, n=4):
    cols = st.columns(n)
    for col, (_, r) in zip(cols, df.head(n).iterrows()):
        pills = [("Rent", money(r["median_rent_weekly"]) + "/wk"), ("Yield", num(r["gross_yield_pct"], "{:.2f}", "%")),
                 ("Growth 10y", num(r["rent_cagr_10y_pct"], suffix="%/yr")), ("Crime", num(r["crime_per_1000_residents"], "{:.0f}", "/1k"))]
        with col:
            card(f'<div class="snap"><div class="name">{esc(r["sa2_name"])}</div><div class="type">{esc(r.get("area_type") or "")}</div>'
                 + badge_html(badges(r)[:3]) + "<div>" + "".join(f'<span class="pill">{k} <b>{esc(v)}</b></span>' for k, v in pills) + "</div></div>")


# ---------- views ----------
FAMILY_RULE = "a Year 1 school and a mapped public playground inside the area, and crime at or below the Auckland median"
QUICK = {
    "Best opportunities": (lambda: RANKED.sort_values("rank_Balanced"),
                           "Balanced rank in the File 4 research screen (481 house-dominated areas, value + growth + risk). Not investment advice."),
    "Highest yield": (lambda: RANKED.sort_values("gross_yield_pct", ascending=False),
                      "Gross yield (2024 CV proxy) among the 481 screened house-dominated areas; apartment areas are left out because small units inflate it."),
    "Most growing": (lambda: RANKED.sort_values("rent_cagr_10y_pct", ascending=False),
                     "10-year rent growth, % a year, among the 481 screened areas. Past performance: read it next to the 2-year trend."),
    "Lowest recorded victimisation rates": (lambda: READY[~READY["flag_crime_hotspot"]].sort_values("crime_per_1000_residents"),
                       "Lowest recorded victimisations per 1,000 residents, analysis-ready areas. Counted where crime happens; crimes inside homes other than burglary are not in the data."),
    "Highest crime": (lambda: READY.sort_values("crime_per_1000_residents", ascending=False),
                      "Highest recorded victimisations per 1,000 residents. Town centres and malls rank high because visitors are not residents."),
    "Lowest risk": (lambda: RANKED.sort_values("risk_score", ascending=False),
                    "Highest risk score (= lowest risk) in the File 4 screen: crime, rent volatility, CV fall and rental depth."),
    "Family friendly": (lambda: READY[~READY["flag_crime_hotspot"] & (READY["year1_schools_in_area"] > 0) & (READY["playgrounds_in_area"] > 0)
                                      & (READY["crime_per_1000_residents"] <= READY["crime_per_1000_residents"].median())]
                        .sort_values("pct_under_15", ascending=False),
                        f"Areas with {FAMILY_RULE}, sorted by share of children under 15. A starting list, not a rating. Playgrounds come from OpenStreetMap."),
}


def view_overview():
    card('<div class="hero"><div class="kicker">Property intelligence</div><h1>Auckland property, suburb by suburb</h1>'
         f'<p>Rent, valuations, risk and community for {len(S)} Stats NZ SA2 areas. Data to September 2026.</p></div>')
    rm, sales = D["rent_m"], D["sales"]
    last3 = rm.tail(3)
    sales_ok = sales[~sales["provisional"]]
    latest, peak = sales_ok.iloc[-1], sales_ok.loc[sales_ok["median_sale_price"].idxmax()]
    kpis([
        ("Areas", f"{len(S)}", "Stats NZ SA2 areas in Auckland", GREEN),
        ("Analysis-ready", f"{len(READY)}", f"{100 * READY['population_2023'].sum() / S['population_2023'].sum():.1f}% of residents; "
         f"{READY['median_rent_weekly'].isna().sum()} have no all-dwelling rent estimate", GREEN),
        ("Avg. of monthly rent medians", f"${last3['median_rent'].mean():,.0f}/wk", f"MBIE, new tenancies, {last3['month'].iloc[0]:%b}–{last3['month'].iloc[-1]:%b %Y}", AMBER),
        ("Median sale price", money(latest["median_sale_price"]),
         f"HUD, Auckland-wide, {latest['quarter_end'].year} Q{latest['quarter_end'].quarter}; "
         f"{latest['median_sale_price'] / peak['median_sale_price'] - 1:+.0%} from peak", AMBER),
        ("CV change 2021–24", f"{READY['cv_change_2021_2024_pct'].median():+.2f}%", "Median SA2; council valuations, not prices", BLUE),
        ("Residents", f"{S['population_2023'].sum():,.0f}", "2023 Census", BLUE),
    ])

    st.markdown("#### Quick search")
    if "qs" not in st.session_state:
        st.session_state.qs = "Best opportunities"
    for col, name in zip(st.columns(len(QUICK)), QUICK):
        if col.button(name, use_container_width=True, type="primary" if st.session_state.qs == name else "secondary"):
            st.session_state.qs = name
            st.rerun()
    fn, desc = QUICK[st.session_state.qs]
    df = fn().dropna(subset=["median_rent_weekly"]) if st.session_state.qs not in ("Lowest recorded victimisation rates", "Highest crime") else fn().dropna(subset=["crime_per_1000_residents"])
    shortlist_table(df)
    caveat(f"{st.session_state.qs}: {desc} {len(df)} areas qualify.")

    st.markdown("#### Executive snapshot")
    snapshot_cards(df)
    st.plotly_chart(risk_return(set(df.head(15)["sa2_code"]), f"{st.session_state.qs} (top 15)"), use_container_width=True)
    caveat("Each bubble is one of the 481 ranked areas, sized by population. Return = mean of the value (yield) and growth (rent, population) "
           "percentiles; risk = 100 − the risk percentile (crime, rent volatility, CV fall, rental depth). Percentiles are relative to these 481 areas. "
           "A research screen, not investment advice.")


def positioning(r):
    s = [f"{r.name} is {'an' if str(r.get('area_type', ''))[:1] in 'AEIOU' else 'a'} {str(r.get('area_type') or 'Auckland').lower()} area "
         f"with {r['population_2023']:,.0f} residents (2023 Census)."]
    if pd.notna(r["median_rent_weekly"]):
        s.append(f"New-tenancy rent of {money(r['median_rent_weekly'])} a week is higher than {pct_rank('median_rent_weekly', r['median_rent_weekly'])}% of analysis-ready areas")
        if pd.notna(r["median_cv_2024"]):
            s[-1] += f", and the 2024 council valuation of {money(r['median_cv_2024'])} is higher than {pct_rank('median_cv_2024', r['median_cv_2024'])}%"
        s[-1] += "."
    if pd.notna(r["rent_cagr_10y_pct"]):
        s.append(f"Rent grew {r['rent_cagr_10y_pct']:.1f}% a year over 10 years"
                 + (f" and has moved {r['cooling_pa']:+.1f}% a year over the last two." if pd.notna(r["cooling_pa"]) else "."))
    if r["crime_rating"] in ("Low", "Moderate", "High"):
        s.append(f"Recorded crime is {r['crime_rating'].lower()} for Auckland ({r['crime_per_1000_residents']:.0f} victimisations per 1,000 residents).")
    elif r["crime_rating"] == "Hotspot":
        s.append("It is a crime hotspot (a centre with many visitors), so its rate per resident is not comparable.")
    return " ".join(s)


def view_explore():
    r = R
    card(f'<div class="kicker">{esc(r.get("area_type") or "SA2")} · SA2 {int(r["sa2_code"])}</div><h2 style="margin:6px 0">{esc(suburb)}</h2>'
         + badge_html(badges(r)) + f'<p style="margin-top:8px">{esc(positioning(r))}</p>')
    kpis([
        ("Weekly rent", money(r["median_rent_weekly"]), "New tenancies, last 4 quarters", AMBER),
        ("Capital value 2024", money(r["median_cv_2024"]), "Council valuation, not a sale price", AMBER),
        ("Gross yield", num(r["gross_yield_pct"], "{:.2f}", "%"), "2024 CV proxy, before costs", BLUE),
        ("Rent growth 10y", num(r["rent_cagr_10y_pct"], suffix="%/yr"), "Past performance", GREEN),
        ("Crime /1,000", num(r["crime_per_1000_residents"], "{:.0f}"), f"Rating: {r['crime_rating']}", RED),
    ])
    t1, t2, t3, t4, t5 = st.tabs(["Growth & Trends", "Risk & Rental", "Crime insights", "People & Community", "Amenities & Lifestyle"])

    with t1:
        kpis([
            ("Rent growth 10y", num(r["rent_cagr_10y_pct"], suffix="%/yr"), "Compound, % a year", GREEN),
            ("Rent trend 2y", num(r["cooling_pa"], "{:+.1f}", "%/yr"), "Last 2 years, annualised; noisy", BLUE),
            ("Rent change 5y", num(r["rent_change_5y_pct"], "{:+.1f}", "%"), "Total change", BLUE),
            ("Outlook, year 1", money(r.get("forecast_rent_y1")), f"{r.get('year1_period') or ''}; 80% band {money(r.get('y1_low'))}–{money(r.get('y1_high'))}", AMBER),
            ("Outlook, year 2", money(r.get("forecast_rent_y2")), f"{r.get('year2_period') or ''}; 80% band {money(r.get('y2_low'))}–{money(r.get('y2_high'))}", AMBER),
        ])
        ts = D["rent_ts"][D["rent_ts"]["sa2_code"] == r["sa2_code"]].sort_values("quarter")
        if ts.empty:
            st.info("No published rent series for this area.")
        else:
            fig = go.Figure(go.Scatter(x=ts["quarter"], y=ts["median_rent"], name="Quarterly median", line=dict(color=SERIES[0], width=2),
                                       hovertemplate="%{x|%b %Y}: $%{y:,.0f}<extra></extra>"))
            if pd.notna(r.get("forecast_rent_y1")):
                last = D["rent_ts"]["quarter"].max()
                xs = [last + pd.DateOffset(months=9), last + pd.DateOffset(months=21)]   # middle of each forecast year
                ys = [r["forecast_rent_y1"], r["forecast_rent_y2"]]
                fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", name="Outlook (80% band)", marker=dict(color=SERIES[1], size=9),
                                         error_y=dict(type="data", symmetric=False, array=[r["y1_high"] - ys[0], r["y2_high"] - ys[1]],
                                                      arrayminus=[ys[0] - r["y1_low"], ys[1] - r["y2_low"]], color=SERIES[1]),
                                         hovertemplate="$%{y:,.0f}<extra>outlook</extra>"))
            fig.update_yaxes(tickprefix="$")
            st.plotly_chart(style(fig, 360, "Weekly rent, new tenancies"), use_container_width=True)
        caveat("Outlook: Auckland's damped rent trend applied to this area's current rent (File 8); about 5% typical error in a one-year backtest, "
               "and 1 area in 5 lands outside its band." + (" Series shared with neighbouring areas." if on(r, "flag_borrowed_rent") else ""))

    with t2:
        if on(r, "ranked"):
            kpis([
                ("Value score", num(r["value_score"], "{:.0f}"), "Percentile: gross yield", GREEN),
                ("Growth score", num(r["growth_score"], "{:.0f}"), "Percentile: rent growth, population", BLUE),
                ("Risk score", num(r["risk_score"], "{:.0f}"), f"100 = lowest risk · {r.get('risk_tier')}", RED),
                ("Screen rank", f"{int(r['rank_Balanced'])} of {len(RANKED)}",
                 f"Range across weightings {int(min(r['rank_Balanced'], r['rank_Income-focused'], r['rank_Cautious']))}–"
                 f"{int(max(r['rank_Balanced'], r['rank_Income-focused'], r['rank_Cautious']))}", AMBER),
            ])
            parts = {"Gross yield": "s_gross_yield_pct", "Rent growth 10y": "s_rent_cagr_10y_pct", "Population change": "s_pop_change_2018_2023_pct",
                     "Crime": "s_crime_per_1000_residents", "Rent volatility": "s_rent_volatility", "CV change": "s_cv_change_2021_2024_pct",
                     "Rental depth": "s_bonds_per_sa2"}
            fig = go.Figure(go.Bar(x=[r[c] for c in parts.values()], y=list(parts), orientation="h", marker_color=SERIES[0],
                                   hovertemplate="%{y}: %{x:.0f}<extra></extra>"))
            fig.update_xaxes(range=[0, 100], title="Percentile among 481 (100 = best for an investor)")
            st.plotly_chart(style(fig, 300, "Risk and return breakdown"), use_container_width=True)
            caveat("A research screen, not investment advice. Scores are relative to the 481 ranked areas.")
        else:
            card(f"<h4>Not in the investment screen</h4><p>{esc(r.get('not_ranked_reason') if pd.notna(r.get('not_ranked_reason')) else 'Only analysis-ready, house-dominated areas (50%+ separate houses) with all seven inputs are ranked.')}</p>")
        gap = f"{r['rent_premium_pct']:+.1f}%" if on(r, "in_premium_analysis") else "—"
        kpis([
            ("Baseline rent (census)", money(r["census_median_rent_weekly"]), "All renting households, March 2023", AMBER),
            ("Bond rent now", money(r["median_rent_weekly"]), "New tenancies, last 4 quarters", AMBER),
            ("Gross yield", num(r["gross_yield_pct"], "{:.2f}", "%"), "2024 CV proxy, before costs", BLUE),
            ("New-tenancy gap 2023", gap, "Bond rent vs census rent; two populations, not a tenant discount", BLUE),
            ("Rent volatility", num(r.get("rent_volatility"), suffix=" pts"), "Std dev of yearly change; high often means a thin market", RED),
        ])

    with t3:
        kpis([
            ("Total crimes", num(r["crime_total"], "{:,.0f}"), "Recorded victimisations, latest 12 months", RED),
            ("Property crimes", num(r["crime_property"], "{:,.0f}"), "Burglary and theft", RED),
            ("Person crimes", num(r["crime_person"], "{:,.0f}"), "Assault, harm, sexual offences, robbery", RED),
            ("Crime /1,000", num(r["crime_per_1000_residents"], "{:.0f}"), f"Rating: {r['crime_rating']}", RED),
        ])
        st.markdown(badge_html([(f"Crime rating: {r['crime_rating']}", {"Low": "ok", "Moderate": "warn", "High": "bad", "Hotspot": "bad"}.get(r["crime_rating"], "info"))]),
                    unsafe_allow_html=True)
        cats = {"Theft": "crime_theft", "Burglary": "crime_burglary", "Assault": "crime_assault", "Harm or endanger": "crime_harm_or_endanger_persons",
                "Robbery": "crime_robbery", "Sexual offences": "crime_sexual_offences"}
        vals = pd.Series({k: r[c] for k, c in cats.items()}).sort_values()
        fig = go.Figure(go.Bar(x=vals.values, y=vals.index, orientation="h", marker_color=SERIES[7], hovertemplate="%{y}: %{x:,.0f}<extra></extra>"))
        st.plotly_chart(style(fig, 300, "Recorded victimisations by type, latest 12 months"), use_container_width=True)
        caveat("NZ Police victimisations (Oct 2025 – Sep 2026), counted where the crime happened and divided by the people who live there, so "
               "busy centres look worse. Police data leaves out crimes inside homes other than burglary. Ratings are thirds of analysis-ready, "
               "non-hotspot areas; hotspots (over 300 per 1,000) are not rated.")

    with t4:
        kpis([
            ("Residents", f"{r['population_2023']:,.0f}", f"{num(r['pop_change_2018_2023_pct'], '{:+.1f}', '%')} since 2018", GREEN),
            ("Median age", num(r["median_age"]), "2023 Census", BLUE),
            ("Household income", money(r["median_household_income"]), "Median, all households", AMBER),
            ("Owner-occupied", num(r["pct_owner_occupied"], suffix="%"), "Of households", BLUE),
            ("Under 15", num(r["pct_under_15"], suffix="%"), "Of residents", GREEN),
            ("Crowded", num(r["pct_crowded"], suffix="%"), "Households needing a bedroom", RED),
        ])
        mix = {"European": "pct_european", "Māori": "pct_maori", "Pacific": "pct_pacific", "Asian": "pct_asian",
               "Christian": "pct_christian", "No religion": "pct_no_religion", "Hindu": "pct_hindu", "Muslim": "pct_muslim", "Buddhist": "pct_buddhist"}
        w = S["population_2023"]
        akl = {k: (S[c] * w).sum() / w[S[c].notna()].sum() for k, c in mix.items()}
        fig = go.Figure([go.Bar(y=list(mix), x=[r[c] for c in mix.values()], orientation="h", name=suburb, marker_color=SERIES[0]),
                         go.Bar(y=list(mix), x=list(akl.values()), orientation="h", name="Auckland (population-weighted)", marker_color="#cbd5e1")])
        fig.update_layout(barmode="group", bargap=0.25)
        fig.update_yaxes(autorange="reversed"); fig.update_xaxes(ticksuffix="%")
        st.plotly_chart(style(fig, 420, "Ethnicity and religion, 2023 Census"), use_container_width=True)
        caveat("Multi-response: one person can count in several groups, so shares can add to more than 100%. Census shares show where people "
               "live, not where mosques, temples, halal shops or faith schools are.")

    with t5:
        rows = [
            ("Primary schools", "primary_schools_in_area", "nearest_primary_school", "km_to_nearest_primary_school"),
            ("Year 1 schools", "year1_schools_in_area", "nearest_year1_school", "km_to_nearest_year1_school"),
            ("Secondary schools", "secondary_schools_in_area", "nearest_secondary_school", "km_to_nearest_secondary_school"),
            ("GP clinics (OSM)", "gp_clinics_in_area", "nearest_gp_clinic", "km_to_nearest_gp_clinic"),
            ("Mosques (verified list of 6)", "mosques_in_area", "nearest_mosque", "km_to_nearest_mosque"),
            ("Halal butchers (OSM)", "halal_butchers_in_area", "nearest_halal_butcher", "km_to_nearest_halal_butcher"),
            ("Parks (OSM)", "parks_in_area", "nearest_park", "km_to_nearest_park"),
            ("Public playgrounds (OSM)", "playgrounds_in_area", "nearest_playground", "km_to_nearest_playground"),
        ]
        st.dataframe(pd.DataFrame([(a, "—" if pd.isna(r[n]) else int(r[n]), r[b] if pd.notna(r[b]) else "—", num(r[k], suffix=" km"))
                                   for a, n, b, k in rows], columns=["Facility", "Inside this area", "Nearest", "Distance"]),
                     hide_index=True, use_container_width=True)
        kpis([
            ("Al-Madinah School", num(r["km_to_al_madinah_coed"], suffix=" km"), "Co-educational, Māngere", GREEN),
            ("Zayed College for Girls", num(r["km_to_zayed_college_girls"], suffix=" km"), "Girls, Years 7–15, Māngere", GREEN),
            ("Stops within 800 m", num(r["pt_stops_800m"], "{:.0f}"), "Bus, train, ferry; frequency not counted", BLUE),
        ])
        if pd.notna(r["nearest_year1_school_authority"]):
            caveat(f"Nearest Year 1 school: {r['nearest_year1_school_authority']}, enrolment scheme: {r['nearest_year1_school_enrolment_scheme']}. "
                   "Nearest is not the zoned school.")
        caveat("Counts are inside the area's boundary; a 0 means none mapped there, not none nearby. GPs, halal butchers, parks and playgrounds "
               "come from OpenStreetMap, which may be incomplete (school, childcare and private playgrounds left out). Mosques come from a verified "
               "list of 6; many Auckland mosques are not in it. Distances are straight-line from the area's centre, not travel time.")


def view_compare():
    st.markdown("## Compare suburbs")
    if not compare:
        st.info("Pick suburbs in the sidebar.")
        return
    rows = BY_NAME.loc[compare]
    colour = {n: SERIES[i] for i, n in enumerate(compare)}
    ts = D["rent_ts"][D["rent_ts"]["sa2_code"].isin(rows["sa2_code"])].merge(S[["sa2_code", "sa2_name"]], on="sa2_code")
    ts = ts[ts["quarter"] >= "2010-01-01"]
    fig = go.Figure([go.Scatter(x=g["quarter"], y=g["median_rent"], name=n, line=dict(color=colour[n], width=2),
                                hovertemplate=f"{esc(n)}: $%{{y:,.0f}}<extra></extra>") for n, g in ts.groupby("sa2_name")])
    fig.update_yaxes(tickprefix="$"); fig.update_layout(hovermode="x unified")
    st.plotly_chart(style(fig, 380, "Quarterly median rent, new tenancies, since 2010"), use_container_width=True)
    shared = rows[rows["rent_source_sa2"].duplicated(keep=False)]
    if len(shared):
        caveat(f"{', '.join(shared.index)} share one rent series, so their lines overlap.")

    spec = [("Area type", lambda r: r.get("area_type") or "—"), ("Capital value 2024", lambda r: money(r["median_cv_2024"])),
            ("Weekly rent (new tenancies)", lambda r: money(r["median_rent_weekly"])),
            ("3-bed house rent", lambda r: money(r["rent_3bed_house"]) + (" (verify)" if on(r, "flag_verify_3bed_house") else "")),
            ("Gross yield (2024 CV proxy)", lambda r: num(r["gross_yield_pct"], "{:.2f}", "%")),
            ("Rent growth 10y", lambda r: num(r["rent_cagr_10y_pct"], suffix="%/yr")), ("Rent trend 2y", lambda r: num(r["cooling_pa"], "{:+.1f}", "%/yr")),
            ("Outlook, year to Sep 2027", lambda r: money(r.get("forecast_rent_y1"))),
            ("Crime /1,000 residents", lambda r: num(r["crime_per_1000_residents"], "{:.0f}")), ("Crime rating", lambda r: r["crime_rating"]),
            ("Screen rank (of 481)", lambda r: num(r.get("rank_Balanced"), "{:.0f}")), ("Residents 2023", lambda r: f"{r['population_2023']:,.0f}"),
            ("Median household income", lambda r: money(r["median_household_income"])), ("Owner-occupied", lambda r: num(r["pct_owner_occupied"], suffix="%")),
            ("Under 15", lambda r: num(r["pct_under_15"], suffix="%")), ("Muslim", lambda r: num(r["pct_muslim"], suffix="%"))]
    st.dataframe(pd.DataFrame({n: [f(rows.loc[n]) for _, f in spec] for n in compare}, index=[k for k, _ in spec]), use_container_width=True)

    # Three measures in three units: small multiples, never one shared axis
    fig = make_subplots(rows=1, cols=3, subplot_titles=["Rent growth 10y, %/yr", "Gross yield, %", "Crime per 1,000 residents"])
    for i, c in enumerate(["rent_cagr_10y_pct", "gross_yield_pct", "crime_per_1000_residents"], 1):
        fig.add_trace(go.Bar(x=compare, y=rows[c], marker_color=[colour[n] for n in compare], showlegend=False,
                             hovertemplate="%{x}: %{y:.2f}<extra></extra>"), row=1, col=i)
    fig.update_xaxes(showticklabels=False)
    st.plotly_chart(style(fig, 330, "Growth, yield and crime"), use_container_width=True)
    caveat("Bar colours follow the rent chart above. Crime is recorded victimisations per resident, so centres with many visitors look worse.")


def view_opportunity():
    st.markdown("## Opportunity finder")
    c = st.columns(3)
    budget = c[0].slider("Max capital value (CV 2024)", 500_000, 3_000_000, 3_000_000, 50_000, format="$%d")
    min_yield = c[1].slider("Min gross yield (%)", 2.5, 6.0, 2.5, 0.25)
    max_crime = c[2].select_slider("Max crime per 1,000 residents", options=list(range(20, 101, 10)), value=100, format_func=lambda v: f"< {v}")
    c = st.columns(3)
    min_growth = c[0].slider("Min rent growth, 10y (% a year)", 0.0, 6.0, 0.0, 0.5)
    types = c[1].multiselect("Area type", sorted(S["area_type"].dropna().unique()), default=sorted(S["area_type"].dropna().unique()))
    hide = c[2].toggle("Hide high risk / crime hotspots", value=True)
    unranked = c[2].checkbox("Also show unranked areas (risk unknown)", value=False, disabled=not hide)

    base = READY.dropna(subset=["median_cv_2024", "gross_yield_pct", "crime_per_1000_residents", "rent_cagr_10y_pct"])
    m = base[(base["median_cv_2024"] <= budget) & (base["gross_yield_pct"] >= min_yield) & (base["crime_per_1000_residents"] < max_crime)
             & (base["rent_cagr_10y_pct"] >= min_growth) & base["area_type"].isin(types)]
    if hide:
        # Unranked areas have no risk tier, so "not Higher risk" would wrongly pass them; keep them only on request
        ranked = m["rank_Balanced"].notna()
        m = m[~m["flag_crime_hotspot"] & ((ranked & (m["risk_tier"] != "Higher risk")) | (~ranked & unranked))]
    m = m.sort_values(["rank_Balanced", "gross_yield_pct"], ascending=[True, False], na_position="last")
    kpis([
        ("Matches", f"{len(m)}", f"of {len(base)} areas with all four measures", GREEN),
        ("Median rent of matches", money(m["median_rent_weekly"].median()), "New tenancies", AMBER),
        ("Median yield of matches", num(m["gross_yield_pct"].median(), "{:.2f}", "%"), "2024 CV proxy", BLUE),
        ("Distinct rent areas", f"{m['rent_source_sa2'].nunique()}", "Independent rent observations behind the matches", RED),
    ])
    if m.empty:
        st.info("No area matches. Loosen a filter.")
        return
    st.markdown("#### Best matches")
    snapshot_cards(m, min(3, len(m)))
    st.plotly_chart(risk_return(set(m["sa2_code"]), "Matches"), use_container_width=True)
    caveat("Only matches that are in the File 4 screen (house-dominated, all seven inputs) appear on the chart. "
           "'Hide high risk' drops crime hotspots and the screen's 'Higher risk' third, and keeps only ranked areas unless you also show "
           "unranked ones. Unranked areas (mostly apartment and inner-city) are not in the risk screen, so their risk is unknown.")
    shortlist_table(m, 50)
    caveat("Ranked by the Balanced screen rank, then yield. Capital value is the council's 2024 valuation (median of all rating units), not a "
           "sale price. A research screen, not investment advice.")


def family_screen(max_rent, dwelling, beds, include_apt=False):
    """Same rules as File 3 Step 8 shortlist() (include_apt=False): all filtered SA2s with the rent for this home and its check status."""
    bt = D["by_type"]
    r = bt[(bt["dwelling"] == dwelling) & (bt["beds"] == beds)][
        ["sa2_code", "rent", "rent_min_quarter", "rent_max_quarter", "lodged_bonds_4q", "flag_thin_sample", "flag_unstable_rent"]]
    keep = ~READY["flag_crime_hotspot"] & (include_apt | (READY["area_type"] != "Apartments & inner city"))
    s = READY[keep].merge(r, on="sa2_code", how="left")
    s["check"] = "ok"
    s.loc[s["flag_thin_sample"].eq(True) | s["flag_unstable_rent"].eq(True), "check"] = "verify"
    s.loc[s["rent"].isna(), "check"] = "no estimate"
    s["under"] = s["rent"] <= max_rent
    return s


def view_family():
    st.markdown("## Family screen")
    caveat("Caps the rent of the home you ask for (dwelling type × bedrooms), never the all-dwelling median. Areas with no published rent "
           "for that home are listed separately, never dropped. Crime hotspots are left out; apartment and inner-city areas are left out "
           "unless you include them (on by default for Apartment searches).")
    c = st.columns(4)
    max_rent = c[0].number_input("Budget ($/wk)", 200, 2000, 580, 10)
    dwelling = c[1].selectbox("Dwelling", ["House", "Apartment", "Flat", "ALL"], format_func=lambda x: "Any type" if x == "ALL" else x)
    beds = c[2].selectbox("Bedrooms", ["1", "2", "3", "4", "5+", "ALL"], index=2, format_func=lambda x: "Any" if x == "ALL" else x)
    groups = {"pct_muslim": "Muslim", "pct_hindu": "Hindu", "pct_christian": "Christian", "pct_buddhist": "Buddhist",
              "pct_pacific": "Pacific", "pct_asian": "Asian", "pct_maori": "Māori", "pct_under_15": "Children under 15"}
    sort = c[3].selectbox("Sort by share of", list(groups), format_func=groups.get)
    # key per dwelling so the default resets when the dwelling changes
    include_apt = st.checkbox("Include apartment & inner-city areas", value=dwelling == "Apartment", key=f"apt_{dwelling}")

    s = family_screen(max_rent, dwelling, beds, include_apt)
    under = s[s["under"]]
    ok = under[under["check"] == "ok"]
    missing = s[s["check"] == "no estimate"]
    kpis([
        ("Areas pass other filters", f"{len(s)}", f"{s['rent'].notna().sum()} have a rent estimate for this home", GREEN),
        ("Under budget", f"{len(under)}", f"On published figures; {under['rent_source_sa2'].nunique()} distinct MBIE rent areas", AMBER),
        ("Confirmed", f"{len(ok)}", f"Pass sample checks; {len(under) - len(ok)} need verifying", BLUE),
        ("No estimate", f"{len(missing)}", "No published rent for this home: neither in nor out", RED),
    ])
    if beds == "1":
        caveat(D["by_type"].loc[D["by_type"]["beds"] == "1", "data_note"].dropna().iloc[0])

    cols = {"sa2_name": "Area", "area_type": "Area type", sort: f"{groups[sort]} %", "rent": "Rent $/wk", "check": "Check",
            "rent_min_quarter": "Lowest qtr", "rent_max_quarter": "Highest qtr", "lodged_bonds_4q": "New bonds (4q)",
            "crime_per_1000_residents": "Crime /1,000", "year1_schools_in_area": "Year 1 schools in area",
            "gp_clinics_in_area": "GPs mapped in area", "playgrounds_in_area": "Playgrounds in area",
            "km_to_nearest_mosque": "Km to mosque (verified list)", "km_to_nearest_halal_butcher": "Km to halal butcher (OSM)",
            "pt_stops_800m": "Stops ≤800 m"}
    cfg = {c: st.column_config.NumberColumn(format="%.1f") for c in [f"{groups[sort]} %", "Km to mosque (verified list)", "Km to halal butcher (OSM)"]}
    cfg.update({c: st.column_config.NumberColumn(format="$%.0f") for c in ["Rent $/wk", "Lowest qtr", "Highest qtr"]})
    cfg["Crime /1,000"] = st.column_config.NumberColumn(format="%.0f")

    def show(df):
        st.dataframe(df[list(cols)].rename(columns=cols), hide_index=True, use_container_width=True, column_config=cfg)

    st.markdown("#### Under budget")
    if under.empty:
        st.info("No area is under budget on the published figures.")
    else:
        show(under.sort_values(sort, ascending=False))
    caveat("Check: ok = 30+ new bonds over 4 quarters and a stable quarterly median; verify = thin or unstable sample, check the Tenancy "
           "Services market rent tool or listings before calling it a match. Rent is new-tenancy bond rent, mean of the last 4 quarters.")
    with st.expander("Cheapest confirmed (ok) estimates for this home"):
        show(s[s["check"] == "ok"].nsmallest(15, "rent"))
    with st.expander(f"No estimate ({len(missing)})"):
        show(missing.sort_values(sort, ascending=False))
    caveat("Census shares show where people live, not where mosques or halal shops are. Mosque distances come from a verified list of 6; "
           "GPs, halal food and playgrounds come from OpenStreetMap, which may be incomplete. Distances are straight-line.")


MAP_METRICS = {
    "median_cv_2024": ("Capital value 2024 ($)", "Council valuation, 1 May 2024; not a sale price; mixes property types, including commercial.", "seq", ":$,.0f"),
    "median_rent_weekly": ("Weekly rent, new tenancies ($)", "Mean of the last 4 quarters, all dwelling types. 142 areas share a figure with a neighbour.", "seq", ":$,.0f"),
    "gross_yield_pct": ("Gross yield, 2024 CV proxy (%)", "New-tenancy rent over council CV, before costs. Inflated in apartment areas.", "seq", ":.2f"),
    "rent_cagr_10y_pct": ("Rent growth, 10 years (% a year)", "Past performance.", "seq", ":.1f"),
    "cooling_pa": ("Rent trend, last 2 years (% a year)", "Annualised; noisy.", "div", ":.1f"),
    "crime_per_1000_residents": ("Crime rate per 1,000 residents", "Recorded victimisations; busy centres look worse because visitors are not residents.", "seq", ":.0f"),
    "pct_muslim": ("Muslim share (%)", "2023 Census. Where people live, not where mosques or halal shops are.", "seq", ":.1f"),
    "km_to_nearest_mosque": ("Mosque distance (km, verified list)", "From a verified list of 6 mosques; many are not in it. Straight-line.", "seq", ":.1f"),
}


def view_map():
    st.markdown("## Map lab")
    key = st.selectbox("Metric", list(MAP_METRICS), format_func=lambda k: MAP_METRICS[k][0])
    label, cav, scale, fmt = MAP_METRICS[key]
    left, right = st.columns([3, 1.25])
    with left:
        st.plotly_chart(choropleth(READY, key, label, scale, fmt), use_container_width=True)
        caveat(f"{cav} Only the {len(READY)} analysis-ready areas are coloured. Map © OpenStreetMap contributors.")
    with right:
        v = R[key]
        vals = READY[key].dropna()
        distance = key.startswith("km_")
        names = ("Nearest", "Farthest") if distance else ("Highest", "Lowest")
        order = st.radio("Rank by", names, horizontal=True, key=f"order_{key}")  # key per metric: distance defaults to Nearest
        low_first = order in ("Nearest", "Lowest")
        rank = int(((vals < v) if low_first else (vals > v)).sum() + 1) if pd.notna(v) and on(R, "analysis_ready") else None
        dollars = fmt.startswith(":$")
        card(f'<div class="kicker">Selected suburb</div><h4 style="margin-top:6px">{esc(suburb)}</h4>'
             f'<p style="font-size:1.5rem;font-weight:700;margin:4px 0">{esc(money(v) if dollars else num(v, "{:,.1f}"))}</p>'
             f'<p>{esc(label)}</p><p>{esc(f"Rank {rank} of {len(vals)} ({order.lower()} = 1)" if rank else "Not on this map (no value or not analysis-ready)")}</p>')
        top = (READY.nsmallest if low_first else READY.nlargest)(10, key)[["sa2_name", key]].rename(columns={"sa2_name": "Area", key: "Value"})
        st.markdown(f"#### Top 10 · {order.lower()}")
        st.dataframe(top, hide_index=True, use_container_width=True, column_config={"Value": st.column_config.NumberColumn(format="$%d" if dollars else "%.1f")})
        if distance:
            caveat(cav)


def table_cards(text):
    """Turn every markdown table row in a METRIC_RULES section into (title, body) using the header names."""
    rows = [l for l in text.splitlines() if l.startswith("|")]
    if len(rows) < 3:
        return []
    split = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]  # noqa: E731
    head = split(rows[0])
    return [(c[0], "\n\n".join(f"**{h}:** {v}" for h, v in zip(head[1:], c[1:]) if v and v != "—")) for c in map(split, rows[2:])]


def two_columns(cards):
    cols = st.columns(2)
    for i, (t, b) in enumerate(cards):
        with cols[i % 2]:
            md_card(t, b)


def section(rs, prefix):
    return next((v for k, v in rs.items() if k.startswith(prefix)), "")


def view_methodology():
    rs = rules()
    st.markdown("## Methodology")
    caveat("Rendered from METRIC_RULES.md, the project's canonical metric reference.")
    two_columns([("Rules of use", section(rs, "Rules of use")),
                 ("Never say", section(rs, "Never say"))])
    st.markdown("#### Data sources")
    two_columns(table_cards(section(rs, "Data vintages")))
    for title, prefix in [("Investment screen", "Investment screen"), ("Rent forecast", "Rent forecast"), ("Family screen", "Family screen"),
                          ("Auckland headline figures", "Auckland headline figures"), ("Not in the data", "Not in the data")]:
        st.markdown(f"#### {title}")
        two_columns(table_cards(section(rs, prefix)))


def view_glossary():
    rs = rules()
    st.markdown("## Glossary")
    caveat("Every metric's column, definition, sample rule and caveat, rendered from METRIC_RULES.md.")
    for title, prefix in [("Geography and keys", "Geography and keys"), ("Value and price", "Value and price"), ("Rent", "Rent"),
                          ("Rent against census", "Rent against census"), ("Affordability", "Affordability"), ("Risk", "Risk"),
                          ("Population and community", "Population and community")]:
        st.markdown(f"#### {title}")
        two_columns(table_cards(rs.get(title) if title in rs else section(rs, prefix)))


{"Overview": view_overview, "Explore suburb": view_explore, "Compare suburbs": view_compare, "Opportunity finder": view_opportunity,
 "Family screen": view_family, "Map lab": view_map, "Methodology": view_methodology, "Glossary": view_glossary}[view]()
