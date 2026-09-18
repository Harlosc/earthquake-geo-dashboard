# Interactive Earthquake Geo Dashboard

Coursework 1 (Individual) — Data Visualization — Pool 2: Geospatial Visualization with Bokeh

## What this is

A Bokeh Server application for exploring recent global earthquake activity,
modelled on a professional seismic-monitoring dashboard layout. It includes:

**Global filter bar**
- Quick time-range presets (Last 24h / 7 days / 30 days / Custom)
- Date range slider, magnitude range slider, depth range slider
- Region dropdown (derived from coordinates) and risk-category dropdown
- Free-text search across location and region

**KPI cards**
- Total Quakes Tracked, Max Magnitude, Average Depth, Significant Events
  (Mw >= 5.0 or tsunami-flagged) — all update live with the filters

**Map**
- Tile basemap with a Light / Terrain / Satellite switcher
- Bubble mode: circles sized and colour-mapped to magnitude
- Heatmap mode: a live-recomputed hexbin density layer
- Tectonic plate boundary overlay (real public dataset, toggleable)
- Hover tooltips, and click-to-select (map point or table row) to open a
  detail panel

**Charts**
- Seismic activity timeline (daily event counts)
- Magnitude distribution histogram
- Depth vs. magnitude scatter plot

**Tables**
- Top-5-largest table
- Full, sortable event log table (shares the same filtered data source as
  the map and scatter plot)

Data source: [USGS Earthquake Hazards Program](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php)
GeoJSON summary feed (`all_month.geojson` — all earthquakes worldwide, past
30 days, no API key needed).

Tectonic plate boundaries: public dataset by Peter Bird (2003), via the
[fraxen/tectonicplates](https://github.com/fraxen/tectonicplates) GitHub repo.

## What's intentionally different from a typical JS dashboard

Bokeh Server is a Python plotting/dashboarding framework, not a general web
app framework, so a few reference-design elements are approximated rather
than reproduced 1:1:
- **No true modal popup** — clicking a point or row opens a persistent
  "Selected Event" panel on the page instead of a floating dialog.
- **No live basemap source swap** — three tile layers (Light/Terrain/
  Satellite) are pre-loaded and toggled by visibility, since Bokeh tile
  renderers can't swap their source URL on the fly.
- **No draw-a-region-on-map tool** — a Region dropdown (derived from
  coordinates during preprocessing) is used instead of a freehand bounding
  box selector.
- **Table pagination** — the event log table scrolls rather than paginating;
  it's fully sortable by clicking column headers.

## Project structure

```
geo_dashboard/
├── main.py                     # The Bokeh Server app (what "bokeh serve" runs)
├── fetch_data.py                # Pulls fresh data from USGS and writes data/earthquakes.csv
├── data/
│   ├── earthquakes.csv          # Local copy of earthquake data used by the app
│   └── tectonic_plates.geojson  # Public tectonic plate boundary dataset
├── requirements.txt
└── README.md
```

## 1. Setup

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Get fresh data

Run this whenever you want the latest 30 days of earthquakes (no API key required):

```bash
python fetch_data.py
```

This overwrites `data/earthquakes.csv`. A sample file is already included so the
app runs out of the box even before you do this.

## 3. Run locally

```bash
bokeh serve --show main.py
```

or, running it as a directory-style app (as named in the coursework brief):

```bash
bokeh serve --show geo_dashboard/
```

This opens your browser at `http://localhost:5006/main` (or `/geo_dashboard`)
with the live, interactive dashboard.

## 4. Hosting on Render (when ready to move off localhost)

1. Push this project to a GitHub repo.
2. On [render.com](https://render.com), create a **New Web Service** from that repo.
3. Build command: `pip install -r requirements.txt`
4. Start command:
   ```
   bokeh serve main.py --port $PORT --address 0.0.0.0 --allow-websocket-origin=*
   ```
   (For production, replace `--allow-websocket-origin=*` with your actual Render URL,
   e.g. `--allow-websocket-origin=your-app.onrender.com`.)
5. Deploy. Render will give you a public URL you can put in your report.

## Notes for the report

- **Data integration**: `fetch_data.py` pulls live GeoJSON from USGS, flattens
  nested properties/geometry into a tabular CSV, and derives `risk_category`
  and `region` columns during preprocessing.
- **Data cleaning**: the USGS feed mixes non-earthquake seismic events (quarry
  blasts, explosions) in among real earthquakes, tagged via a `type` field.
  `fetch_data.py`'s `clean_data()` step filters the dataset down to
  `event_type == "earthquake"` only, and prints how many records were removed.
  Records missing magnitude or coordinates are also dropped.
- **Region classification**: `classify_region()` buckets each event into a
  broad region (North America, Europe, Asia, etc.) using latitude/longitude
  bounding boxes — a coarse but effective stand-in for full reverse-geocoding,
  used to power the Region filter dropdown.
- **Advanced plotting features**: tile-based basemap with a live switcher,
  Web Mercator projection, linear colour mapping (`LinearColorMapper` +
  `ColorBar`) for choropleth-style intensity, a hexbin density heatmap layer,
  a real tectonic plate boundary overlay, `HoverTool` + `TapTool` for
  click-to-inspect, and multiple linked interactive filters implemented as
  Python callbacks that update a shared `ColumnDataSource` live — this is
  what makes it a true Bokeh **Server** app rather than a static plot.
- **Hosting**: works both via `bokeh serve` on localhost and deployed to Render
  (see above).
- **Challenge — basemap API key**: CartoDB's free tile provider (Positron /
  Dark Matter) started requiring an API key partway through development,
  which showed up as "API KEY REQUIRED" watermarks tiled across the map.
  Switched to Esri's tile providers (`WorldGrayCanvas`, `WorldTopoMap`,
  `WorldImagery`), which are free and require no key.
- **Challenge — layout sizing**: mixing Bokeh's "stretch" and "fixed" sizing
  modes in nested layouts initially collapsed the map to near-zero width.
  Fixed by using explicit fixed widths/heights throughout instead of
  stretch modes.
