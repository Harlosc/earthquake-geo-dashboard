"""
main.py - Interactive Earthquake Geo Dashboard (Bokeh Server App)

Coursework 1 - Pool 2: Geospatial Visualization with Bokeh
Data: USGS Earthquake Hazards Program (past 30 days, all magnitudes)

Run with:
    bokeh serve --show geo_dashboard/

Features:
  - Global filter bar: date range, magnitude range, depth range, region, search
  - KPI cards: total tracked, max magnitude, average depth, significant events
  - Map: tile basemap with switcher (Light/Terrain/Satellite), bubble markers
    colour-mapped to magnitude, hexbin density "heatmap" toggle, tectonic
    plate boundary overlay (public dataset), hover tooltips, click-to-select
  - Charts: seismic activity timeline, magnitude distribution histogram,
    depth vs magnitude scatter
  - Searchable, sortable event log table (capped to the most recent 300
    filtered rows client-side for performance; full result count still
    shown, and any column can be clicked to re-sort - e.g. by magnitude)
  - Selected-event detail panel (click a map point or table row)

Notes on scope: Bokeh Server does not support true floating modal dialogs,
freehand map drawing/bounding-box selection, or swapping live tile sources
without pre-registering them, so those specific reference-design elements are
approximated (a persistent "selected event" panel instead of a modal; a
region dropdown instead of a draw tool; three pre-loaded basemaps toggled by
visibility instead of a live source swap).
"""

import math
import os
import json

import numpy as np
import pandas as pd
from bokeh.io import curdoc
from bokeh.layouts import column, row
from bokeh.models import (
    ColumnDataSource,
    HoverTool,
    TapTool,
    Select,
    DateRangeSlider,
    Div,
    ColorBar,
    LinearColorMapper,
    RangeSlider,
    DataTable,
    TableColumn,
    NumberFormatter,
    InlineStyleSheet,
    RadioButtonGroup,
    CheckboxGroup,
    TextInput,
    Button,
)
from bokeh.plotting import figure
from bokeh.transform import transform
from bokeh.palettes import Turbo256
from bokeh.util.hex import hexbin
import xyzservices.providers as xyz

# ---------------------------------------------------------------------------
# 0. Theme / palette
# ---------------------------------------------------------------------------
curdoc().theme = "light_minimal"

BG = "#f6f8fa"
PANEL = "#ffffff"
BORDER = "#d0d7de"
TEXT = "#1f2328"
MUTED = "#57606a"
ACCENT = "#d16a1f"
ACCENT_RED = "#cf222e"
ACCENT_BLUE = "#0969da"
ACCENT_GREEN = "#1a7f37"
FONT = "'JetBrains Mono', 'Consolas', 'SFMono-Regular', monospace"

HERE = os.path.dirname(__file__)

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
DATA_PATH = os.path.join(HERE, "data", "earthquakes.csv")
raw_df = pd.read_csv(DATA_PATH)
raw_df["time"] = pd.to_datetime(raw_df["time"], format="ISO8601", utc=True).dt.tz_localize(None)

if "region" not in raw_df.columns:
    raw_df["region"] = "Other / Ocean"

# Derived alert level (computed here so it works even on older CSVs that
# predate this column)
def alert_level(row):
    if row.get("tsunami", 0) == 1:
        return "Warning"
    if row["mag"] >= 6.0:
        return "Watch"
    if row["mag"] >= 4.5:
        return "Advisory"
    return "No Threat"


raw_df["alert_level"] = raw_df.apply(alert_level, axis=1)


def lonlat_to_webmercator(lon, lat):
    k = 6378137.0
    x = lon * (k * math.pi / 180.0)
    lat = max(min(lat, 89.9), -89.9)
    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) * k
    return x, y


xs, ys = zip(*[lonlat_to_webmercator(lon, lat) for lon, lat in zip(raw_df["longitude"], raw_df["latitude"])])
raw_df["x"] = xs
raw_df["y"] = ys

raw_df["marker_size"] = raw_df["mag"].clip(lower=0).apply(lambda m: 6 + m * 4)
raw_df["date_str"] = raw_df["time"].dt.strftime("%Y-%m-%d %H:%M UTC")
raw_df["coord_str"] = raw_df.apply(lambda r: f"{r['latitude']:.2f}, {r['longitude']:.2f}", axis=1)

MIN_DATE = raw_df["time"].min()
MAX_DATE = raw_df["time"].max()
MIN_MAG = float(raw_df["mag"].min())
MAX_MAG = float(raw_df["mag"].max())
MIN_DEPTH = float(np.floor(raw_df["depth_km"].min()))
MAX_DEPTH = float(np.ceil(raw_df["depth_km"].max()))

RISK_CATEGORIES = ["All", "Minor", "Light", "Moderate", "High Risk"]
REGIONS = ["All"] + sorted(raw_df["region"].dropna().unique().tolist())

# ---------------------------------------------------------------------------
# 2. Tectonic plate boundaries (public dataset, converted to Web Mercator)
# ---------------------------------------------------------------------------
PLATES_PATH = os.path.join(HERE, "data", "tectonic_plates.geojson")
plate_xs, plate_ys = [], []
if os.path.exists(PLATES_PATH):
    with open(PLATES_PATH) as f:
        plates_geojson = json.load(f)
    for feature in plates_geojson["features"]:
        geom = feature["geometry"]
        coords_list = geom["coordinates"] if geom["type"] == "LineString" else []
        if not coords_list:
            continue
        line_x, line_y = [], []
        for lon, lat in coords_list:
            mx, my = lonlat_to_webmercator(lon, lat)
            line_x.append(mx)
            line_y.append(my)
        plate_xs.append(line_x)
        plate_ys.append(line_y)

plate_source = ColumnDataSource(data=dict(xs=plate_xs, ys=plate_ys))

# ---------------------------------------------------------------------------
# 3. Global page / widget styling
# ---------------------------------------------------------------------------
global_style = Div(text=f"""
<style>
  html, body {{
    background-color: {BG} !important;
    font-family: {FONT} !important;
    margin: 0; padding: 0; width: 100%; min-height: 100vh;
  }}
  .bk-root, #bk-root, .bk-root .bk {{ background-color: {BG} !important; }}
  .bk-Column, .bk-Row {{ font-family: {FONT} !important; }}
</style>
""", width=0, height=0, visible=True, margin=(0, 0, 0, 0))

widget_stylesheet = InlineStyleSheet(css=f"""
  :host {{ font-family: {FONT}; }}
  select, input {{
    background-color: {PANEL} !important;
    color: {TEXT} !important;
    border: 1px solid {BORDER} !important;
    font-family: {FONT} !important;
  }}
  .noUi-target {{ background: #eaeef2 !important; border: 1px solid {BORDER} !important; box-shadow: none !important; }}
  .noUi-connect {{ background: {ACCENT} !important; }}
  .noUi-handle {{ background: {PANEL} !important; border: 2px solid {ACCENT} !important; box-shadow: none !important; }}
  .bk-input-group label, label {{
    color: {MUTED} !important; font-size: 12px !important;
    text-transform: uppercase; letter-spacing: 0.5px;
  }}
""")

button_stylesheet = InlineStyleSheet(css=f"""
  .bk-btn {{
    background-color: {PANEL} !important;
    color: {TEXT} !important;
    border: 1px solid {BORDER} !important;
    font-family: {FONT} !important;
    font-size: 11px !important;
  }}
  .bk-btn.bk-active {{
    background-color: {ACCENT} !important;
    color: white !important;
    border-color: {ACCENT} !important;
  }}
""")

table_stylesheet = InlineStyleSheet(css=f"""
  .slick-header-columns {{
    background-color: {PANEL} !important; color: {ACCENT} !important;
    font-family: {FONT} !important; font-size: 11px !important; text-transform: uppercase;
  }}
  .slick-row {{ background-color: {PANEL} !important; color: {TEXT} !important; font-family: {FONT} !important; }}
  .slick-row:hover {{ background-color: #eaeef2 !important; }}
  .slick-row.selected {{ background-color: #fff1e6 !important; }}
  .slick-cell {{
    border-color: {BORDER} !important; white-space: normal !important;
    line-height: 1.3 !important; display: flex !important; align-items: center !important;
  }}
""")

# ---------------------------------------------------------------------------
# 4. Data sources
# ---------------------------------------------------------------------------
source = ColumnDataSource(raw_df)  # drives map circles, scatter plot, event log table

# ---------------------------------------------------------------------------
# 5. Map figure
# ---------------------------------------------------------------------------
p = figure(
    x_axis_type="mercator",
    y_axis_type="mercator",
    tools="pan,wheel_zoom,box_zoom,reset,save,tap",
    active_scroll="wheel_zoom",
    width=1630,
    height=560,
    background_fill_color=PANEL,
    border_fill_color=BG,
    outline_line_color=BORDER,
)
p.title.text = "GLOBAL EARTHQUAKE ACTIVITY"
p.title.text_font = FONT
p.title.text_color = TEXT
p.title.text_font_size = "13px"
p.title.text_font_style = "bold"
p.grid.grid_line_color = "#e3e8ee"
p.axis.axis_line_color = BORDER
p.axis.major_tick_line_color = BORDER
p.axis.minor_tick_line_color = None
p.axis.major_label_text_color = MUTED

# Base map layers - pre-registered, toggled via visibility (no live source swap in Bokeh)
tile_light = p.add_tile(xyz.Esri.WorldGrayCanvas)
tile_terrain = p.add_tile(xyz.Esri.WorldTopoMap)
tile_satellite = p.add_tile(xyz.Esri.WorldImagery)
tile_terrain.visible = False
tile_satellite.visible = False

# Tectonic plate boundaries overlay
plate_renderer = p.multi_line(
    xs="xs", ys="ys", source=plate_source,
    line_color=ACCENT_RED, line_width=1.2, line_alpha=0.6, line_dash="dashed",
)
plate_renderer.visible = False

color_mapper = LinearColorMapper(palette=Turbo256, low=MIN_MAG, high=max(MAX_MAG, 1))

# Bubble layer (magnitude-sized, magnitude-coloured circles)
circles = p.circle(
    x="x", y="y", size="marker_size", source=source,
    fill_color=transform("mag", color_mapper), fill_alpha=0.8,
    line_color="#0d1117", line_width=0.6,
)

# Heatmap layer (hexbin density) - hidden by default, recomputed on filter change
hex_source = ColumnDataSource(data=dict(q=[], r=[], counts=[]))
HEX_SIZE = 300_000  # meters, roughly matches a few hundred km per hex at this scale
hex_mapper = LinearColorMapper(palette=Turbo256, low=0, high=1)
hex_renderer = p.hex_tile(
    q="q", r="r", source=hex_source, size=HEX_SIZE,
    fill_color=transform("counts", hex_mapper), line_color=None, fill_alpha=0.85,
)
hex_renderer.visible = False

color_bar = ColorBar(
    color_mapper=color_mapper, label_standoff=10, title="Magnitude", location=(0, 0),
    background_fill_color=BG, major_label_text_color=MUTED, title_text_color=MUTED,
)
p.add_layout(color_bar, "right")

hover = HoverTool(
    renderers=[circles],
    tooltips=[
        ("Location", "@place"),
        ("Magnitude", "@mag{0.0}"),
        ("Depth (km)", "@depth_km{0.0}"),
        ("Date", "@date_str"),
        ("Alert", "@alert_level"),
    ],
)
p.add_tools(hover)
p.add_tools(TapTool(renderers=[circles]))

# ---------------------------------------------------------------------------
# 6. Global filter bar
# ---------------------------------------------------------------------------
time_range_buttons = RadioButtonGroup(
    labels=["Last 24 hours", "Last 7 days", "Last 30 days", "Custom"],
    active=2,
    stylesheets=[button_stylesheet],
)

date_slider = DateRangeSlider(
    title="Date range", start=MIN_DATE, end=MAX_DATE, value=(MIN_DATE, MAX_DATE),
    step=1, stylesheets=[widget_stylesheet], width=340,
)

mag_slider = RangeSlider(
    title="Magnitude range", start=math.floor(MIN_MAG), end=math.ceil(MAX_MAG),
    value=(math.floor(MIN_MAG), math.ceil(MAX_MAG)), step=0.1,
    stylesheets=[widget_stylesheet], width=220,
)

depth_slider = RangeSlider(
    title="Depth range (km)", start=min(MIN_DEPTH, 0), end=max(MAX_DEPTH, 1),
    value=(min(MIN_DEPTH, 0), max(MAX_DEPTH, 1)), step=1,
    stylesheets=[widget_stylesheet], width=220,
)

region_select = Select(title="Region", value="All", options=REGIONS, stylesheets=[widget_stylesheet], width=180)
risk_select = Select(title="Risk category", value="All", options=RISK_CATEGORIES, stylesheets=[widget_stylesheet], width=180)

search_input = TextInput(title="Search location or region", placeholder="e.g. Alaska, Japan...", stylesheets=[widget_stylesheet], width=260)

basemap_buttons = RadioButtonGroup(labels=["Light", "Terrain", "Satellite"], active=0, stylesheets=[button_stylesheet])
layer_buttons = RadioButtonGroup(labels=["Bubble", "Heatmap"], active=0, stylesheets=[button_stylesheet])
plates_checkbox = CheckboxGroup(labels=["Show tectonic plate boundaries"], active=[])

# ---------------------------------------------------------------------------
# 7. KPI cards
# ---------------------------------------------------------------------------
def make_card(accent):
    return Div(
        text="", width=260, height=90,
        styles={
            "background-color": PANEL, "border-left": f"4px solid {accent}",
            "border-radius": "6px", "padding": "14px 18px",
            "font-family": FONT, "box-sizing": "border-box",
        },
    )


card_total = make_card(ACCENT_BLUE)
card_max_mag = make_card(ACCENT_RED)
card_avg_depth = make_card(ACCENT)
card_significant = make_card(ACCENT_GREEN)


def render_card(div, label, value, sub, accent):
    div.text = f"""
    <div style="color:{MUTED};font-size:11px;letter-spacing:1px;text-transform:uppercase;">{label}</div>
    <div style="color:{TEXT};font-size:26px;font-weight:700;margin-top:4px;">{value}</div>
    <div style="color:{accent};font-size:11px;margin-top:2px;">{sub}</div>
    """


# ---------------------------------------------------------------------------
# 8. Charts: timeline, magnitude distribution, depth vs magnitude scatter
# ---------------------------------------------------------------------------
def style_chart(fig):
    fig.background_fill_color = PANEL
    fig.border_fill_color = PANEL
    fig.outline_line_color = BORDER
    fig.grid.grid_line_color = "#e3e8ee"
    fig.axis.axis_line_color = BORDER
    fig.axis.major_tick_line_color = BORDER
    fig.axis.minor_tick_line_color = None
    fig.axis.major_label_text_color = MUTED
    fig.axis.axis_label_text_color = MUTED
    fig.title.text_font = FONT
    fig.title.text_color = TEXT
    fig.title.text_font_size = "12px"
    fig.title.text_font_style = "bold"


timeline_source = ColumnDataSource(data=dict(date=[], count=[]))
timeline_fig = figure(
    x_axis_type="datetime", width=530, height=260, title="SEISMIC ACTIVITY TIMELINE",
    tools="pan,wheel_zoom,reset", toolbar_location="above",
)
timeline_fig.line(x="date", y="count", source=timeline_source, line_color=ACCENT, line_width=2)
timeline_fig.scatter(x="date", y="count", source=timeline_source, size=5, fill_color=ACCENT, line_color=None)
style_chart(timeline_fig)

hist_source = ColumnDataSource(data=dict(left=[], right=[], center=[], count=[]))
hist_fig = figure(
    width=530, height=260, title="MAGNITUDE DISTRIBUTION",
    tools="pan,wheel_zoom,reset", toolbar_location="above",
)
hist_fig.quad(
    top="count", bottom=0, left="left", right="right", source=hist_source,
    fill_color=ACCENT_GREEN, line_color=PANEL, fill_alpha=0.85,
)
hist_fig.xaxis.axis_label = "Magnitude"
hist_fig.yaxis.axis_label = "Events"
style_chart(hist_fig)

scatter_fig = figure(
    width=530, height=260, title="DEPTH VS. MAGNITUDE",
    tools="pan,wheel_zoom,reset", toolbar_location="above",
)
scatter_fig.scatter(
    x="depth_km", y="mag", source=source, size=8,
    fill_color=transform("mag", color_mapper), fill_alpha=0.75, line_color="#0d1117", line_width=0.4,
)
scatter_fig.xaxis.axis_label = "Depth (km)"
scatter_fig.yaxis.axis_label = "Magnitude"
style_chart(scatter_fig)

# ---------------------------------------------------------------------------
# 9. Tables
# ---------------------------------------------------------------------------
# Event log is capped client-side to keep large filtered result sets from
# pushing thousands of rows to the browser on every interaction. It's sorted
# most-recent-first by default; click "Magnitude" to sort by size instead
# (this is also what replaced the old separate "Top 5 largest" table).
EVENT_LOG_LIMIT = 300

event_log_source = ColumnDataSource(data=dict(
    place=[], mag=[], depth_km=[], date_str=[], coord_str=[], alert_level=[],
    region=[], risk_category=[], tsunami=[], url=[],
))
event_log_note = Div(text="", styles={"color": MUTED, "font-size": "11px", "margin-bottom": "6px"})

event_log_columns = [
    TableColumn(field="date_str", title="Date / Time (UTC)", width=160),
    TableColumn(field="place", title="Location", width=280),
    TableColumn(field="mag", title="Magnitude", formatter=NumberFormatter(format="0.0"), width=90),
    TableColumn(field="depth_km", title="Depth (km)", formatter=NumberFormatter(format="0.0"), width=90),
    TableColumn(field="coord_str", title="Coordinates", width=160),
    TableColumn(field="alert_level", title="Alert", width=100),
]
event_log_table = DataTable(
    source=event_log_source, columns=event_log_columns, width=1100, height=320,
    row_height=36, stylesheets=[table_stylesheet],
)

# ---------------------------------------------------------------------------
# 10. Selected event detail panel
# ---------------------------------------------------------------------------
selected_panel = Div(
    text=f"""<div style="color:{MUTED};font-size:12px;">
    Click a point on the map or a row in the event log to see details here.
    </div>""",
    width=1660,
    styles={
        "background-color": PANEL, "border": f"1px solid {BORDER}", "border-radius": "6px",
        "padding": "16px", "box-sizing": "border-box", "font-family": FONT, "min-height": "70px",
    },
)


def render_selected_event(d, idx):
    tsunami_flag = "Yes - tsunami flagged" if d["tsunami"][idx] == 1 else "No"
    selected_panel.text = f"""
    <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap;">
      <div>
        <div style="color:{MUTED};font-size:11px;text-transform:uppercase;letter-spacing:1px;">Selected Event</div>
        <div style="color:{TEXT};font-size:18px;font-weight:700;margin-top:2px;">{d['place'][idx]}</div>
        <div style="color:{MUTED};font-size:12px;margin-top:2px;">{d['region'][idx]} &middot; {d['date_str'][idx]}</div>
      </div>
      <div style="text-align:right;">
        <div style="color:{ACCENT_RED};font-size:24px;font-weight:700;">M {d['mag'][idx]:.1f}</div>
        <div style="color:{MUTED};font-size:11px;">{d['risk_category'][idx]}</div>
      </div>
    </div>
    <div style="margin-top:12px; display:flex; gap:32px; flex-wrap:wrap;">
      <div><div style="color:{MUTED};font-size:11px;">DEPTH</div><div style="color:{TEXT};font-size:14px;">{d['depth_km'][idx]:.1f} km</div></div>
      <div><div style="color:{MUTED};font-size:11px;">COORDINATES</div><div style="color:{TEXT};font-size:14px;">{d['coord_str'][idx]}</div></div>
      <div><div style="color:{MUTED};font-size:11px;">TSUNAMI FLAG</div><div style="color:{TEXT};font-size:14px;">{tsunami_flag}</div></div>
      <div><div style="color:{MUTED};font-size:11px;">ALERT LEVEL</div><div style="color:{TEXT};font-size:14px;">{d['alert_level'][idx]}</div></div>
      <div><div style="color:{MUTED};font-size:11px;">SOURCE</div><div style="color:{ACCENT_BLUE};font-size:14px;"><a href="{d['url'][idx]}" target="_blank" style="color:{ACCENT_BLUE};">USGS event page &#8594;</a></div></div>
    </div>
    """


def on_selection_change(attr, old, new):
    if not new:
        selected_panel.text = f"""<div style="color:{MUTED};font-size:12px;">
        Click a point on the map or a row in the event log to see details here.
        </div>"""
        return
    render_selected_event(source.data, new[0])


def on_table_selection_change(attr, old, new):
    if not new:
        return  # leave whatever the map last selected showing
    render_selected_event(event_log_source.data, new[0])


source.selected.on_change("indices", on_selection_change)
event_log_source.selected.on_change("indices", on_table_selection_change)

# ---------------------------------------------------------------------------
# 11. Filtering callback
# ---------------------------------------------------------------------------
def apply_time_preset(attr, old, new):
    if new == 0:
        start = MAX_DATE - pd.Timedelta(hours=24)
    elif new == 1:
        start = MAX_DATE - pd.Timedelta(days=7)
    elif new == 2:
        start = MAX_DATE - pd.Timedelta(days=30)
    else:
        return  # Custom - leave slider as-is
    start = max(start, MIN_DATE)
    date_slider.value = (start, MAX_DATE)


def recompute_heatmap(df):
    """Only called when Heatmap mode is actually the active layer - this used
    to run on every filter change regardless of visibility, which was pure
    wasted computation while Bubble mode was showing."""
    if len(df):
        result = hexbin(df["x"].to_numpy(), df["y"].to_numpy(), size=HEX_SIZE)
        hex_source.data = dict(q=result.q, r=result.r, counts=result.counts)
        hex_mapper.high = max(int(result.counts.max()), 1)
    else:
        hex_source.data = dict(q=[], r=[], counts=[])


def get_filtered_df():
    df = raw_df

    start, end = date_slider.value
    start_ts = pd.to_datetime(start, unit="ms")
    end_ts = pd.to_datetime(end, unit="ms")
    df = df[(df["time"] >= start_ts) & (df["time"] <= end_ts)]

    mag_lo, mag_hi = mag_slider.value
    df = df[(df["mag"] >= mag_lo) & (df["mag"] <= mag_hi)]

    depth_lo, depth_hi = depth_slider.value
    df = df[(df["depth_km"] >= depth_lo) & (df["depth_km"] <= depth_hi)]

    if risk_select.value != "All":
        df = df[df["risk_category"] == risk_select.value]

    if region_select.value != "All":
        df = df[df["region"] == region_select.value]

    term = search_input.value.strip().lower()
    if term:
        df = df[df["place"].str.lower().str.contains(term) | df["region"].str.lower().str.contains(term)]

    return df


def update(attr, old, new):
    df = get_filtered_df()
    source.data = df

    # KPI cards
    render_card(card_total, "Total Quakes Tracked", f"{len(df):,}", f"of {len(raw_df):,} total events", ACCENT_BLUE)

    if len(df):
        render_card(card_max_mag, "Max Magnitude", f"M {df['mag'].max():.1f}", "in current filter", ACCENT_RED)
        render_card(card_avg_depth, "Average Depth", f"{df['depth_km'].mean():.0f} km", "shallow focus" if df['depth_km'].mean() < 70 else "intermediate/deep focus", ACCENT)
    else:
        render_card(card_max_mag, "Max Magnitude", "-", "no matching events", ACCENT_RED)
        render_card(card_avg_depth, "Average Depth", "-", "no matching events", ACCENT)

    significant = df[(df["mag"] >= 5.0) | (df["tsunami"] == 1)]
    render_card(card_significant, "Significant Events", f"{len(significant):,}", "Mw >= 5.0 or tsunami flag", ACCENT_GREEN)

    # Event log: most-recent-first, capped so we're not shipping thousands of
    # rows to the browser on every filter change. Fully sortable by clicking
    # column headers (e.g. click "Magnitude" for a largest-first view).
    log_df = df.sort_values("time", ascending=False).head(EVENT_LOG_LIMIT)
    event_log_source.data = dict(
        place=log_df["place"].tolist(), mag=log_df["mag"].tolist(),
        depth_km=log_df["depth_km"].tolist(), date_str=log_df["date_str"].tolist(),
        coord_str=log_df["coord_str"].tolist(), alert_level=log_df["alert_level"].tolist(),
        region=log_df["region"].tolist(), risk_category=log_df["risk_category"].tolist(),
        tsunami=log_df["tsunami"].tolist(), url=log_df["url"].tolist(),
    )
    if len(df) > EVENT_LOG_LIMIT:
        event_log_note.text = f"Showing the {EVENT_LOG_LIMIT:,} most recent of {len(df):,} filtered events - narrow your filters to see more, or sort by clicking a column header."
    else:
        event_log_note.text = f"Showing all {len(df):,} filtered events."

    # Timeline (daily counts)
    if len(df):
        daily = df.set_index("time").resample("D").size()
        timeline_source.data = dict(date=daily.index, count=daily.values)
    else:
        timeline_source.data = dict(date=[], count=[])

    # Magnitude histogram
    if len(df):
        bins = np.arange(math.floor(df["mag"].min()), math.ceil(df["mag"].max()) + 1, 0.5)
        counts, edges = np.histogram(df["mag"], bins=bins)
        hist_source.data = dict(left=edges[:-1], right=edges[1:], center=(edges[:-1] + edges[1:]) / 2, count=counts)
    else:
        hist_source.data = dict(left=[], right=[], center=[], count=[])

    # Heatmap: only recompute if that layer is actually the one showing
    if layer_buttons.active == 1:
        recompute_heatmap(df)


for w in (risk_select, region_select, date_slider, mag_slider, depth_slider, search_input):
    w.on_change("value", update)

time_range_buttons.on_change("active", apply_time_preset)

update(None, None, None)

# ---------------------------------------------------------------------------
# 12. Layer / basemap toggle callbacks
# ---------------------------------------------------------------------------
def on_basemap_change(attr, old, new):
    tile_light.visible = new == 0
    tile_terrain.visible = new == 1
    tile_satellite.visible = new == 2


def on_layer_change(attr, old, new):
    circles.visible = new == 0
    hex_renderer.visible = new == 1
    if new == 1:
        recompute_heatmap(get_filtered_df())


def on_plates_change(attr, old, new):
    plate_renderer.visible = 0 in new


basemap_buttons.on_change("active", on_basemap_change)
layer_buttons.on_change("active", on_layer_change)
plates_checkbox.on_change("active", on_plates_change)

# ---------------------------------------------------------------------------
# 13. Layout
# ---------------------------------------------------------------------------
def section_label(text):
    return Div(text=f"""<div style="color:{ACCENT};font-size:11px;letter-spacing:1px;
        text-transform:uppercase;margin-bottom:4px;">{text}</div>""")


header = Div(
    text=f"""
    <div style="border-top:3px solid {ACCENT}; padding-top:14px; display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap;">
      <div>
        <div style="color:{TEXT}; font-size:22px; font-weight:700; letter-spacing:1px; font-family:{FONT};">
          EARTHQUAKE MONITORING DASHBOARD
        </div>
        <div style="color:{MUTED}; font-size:12px; margin-top:4px; font-family:{FONT};">
          Data source: USGS Earthquake Hazards Program &middot; GeoJSON feed &middot; past 30 days
          &middot; Tectonic plate boundaries: Peter Bird (2003) via fraxen/tectonicplates
        </div>
      </div>
    </div>
    """,
    width=1660,
)

filter_bar = column(
    section_label("Time range"),
    time_range_buttons,
    row(date_slider, mag_slider, depth_slider, region_select, risk_select, search_input, spacing=20),
    styles={
        "background-color": PANEL, "border": f"1px solid {BORDER}", "border-radius": "6px",
        "padding": "16px", "box-sizing": "border-box",
    },
    width=1660,
)

kpi_row = row(card_total, card_max_mag, card_avg_depth, card_significant)

map_controls = row(
    column(section_label("Base map"), basemap_buttons),
    column(section_label("Layer"), layer_buttons),
    column(section_label("Overlay"), plates_checkbox),
    spacing=30,
)

map_panel = column(
    map_controls,
    p,
    styles={
        "background-color": PANEL, "border": f"1px solid {BORDER}", "border-radius": "6px",
        "padding": "12px", "box-sizing": "border-box",
    },
    width=1660,
)

charts_row = row(timeline_fig, hist_fig, scatter_fig, spacing=20)

event_log_panel = column(
    section_label("Event Log"),
    event_log_note,
    event_log_table,
    width=1660,
    styles={
        "background-color": PANEL, "border": f"1px solid {BORDER}", "border-radius": "6px",
        "padding": "16px", "box-sizing": "border-box",
    },
)

main_layout = column(
    global_style,
    header,
    filter_bar,
    kpi_row,
    map_panel,
    charts_row,
    selected_panel,
    event_log_panel,
    styles={"background-color": BG, "padding": "20px", "box-sizing": "border-box"},
)

curdoc().add_root(main_layout)
curdoc().title = "Earthquake Geo Dashboard"
