"""
fetch_data.py
Downloads recent earthquake data from the USGS Earthquake Hazards Program
public GeoJSON feed and saves it as a clean CSV for use in the Bokeh app.

USGS feeds (no API key required):
https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/

We use the "all_month" feed (all earthquakes, past 30 days) so the dataset
has enough variety in magnitude and location for a meaningful dashboard.
"""

import requests
import pandas as pd
import os

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.geojson"
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "data", "earthquakes.csv")


def fetch_earthquake_data(url: str = USGS_URL) -> pd.DataFrame:
    print(f"Fetching data from: {url}")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    geojson = response.json()

    records = []
    for feature in geojson["features"]:
        props = feature["properties"]
        coords = feature["geometry"]["coordinates"]  # [lon, lat, depth]

        # Skip records with missing essential fields
        if props.get("mag") is None or coords[0] is None or coords[1] is None:
            continue

        records.append({
            "id": feature.get("id"),
            "place": props.get("place"),
            "mag": props.get("mag"),
            "time": pd.to_datetime(props.get("time"), unit="ms", utc=True),
            "longitude": coords[0],
            "latitude": coords[1],
            "depth_km": coords[2] if len(coords) > 2 else None,
            "mag_type": props.get("magType"),
            "sig": props.get("sig"),  # USGS "significance" score
            "tsunami": props.get("tsunami"),
            "url": props.get("url"),
            "event_type": props.get("type"),  # "earthquake", "quarry blast", "explosion", etc.
        })

    df = pd.DataFrame(records)
    return df


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Data cleaning step: the USGS feed mixes in non-earthquake seismic events
    (quarry blasts, explosions, etc.) alongside real earthquakes. For a
    dashboard specifically about earthquake activity, these are dropped here
    rather than left in silently.
    """
    before = len(df)
    df = df[df["event_type"] == "earthquake"].copy()
    removed = before - len(df)
    if removed:
        print(f"Data cleaning: removed {removed} non-earthquake events (quarry blasts, explosions, etc.)")
    return df


def classify_region(lon: float, lat: float) -> str:
    """
    Bucket a coordinate into a broad geographic region using simple
    bounding boxes. This is a coarse classifier (not a full reverse-geocoder)
    but is enough to power a "region" filter dropdown.
    """
    if lat > 15 and -170 <= lon <= -50:
        return "North America"
    if lat <= 15 and -90 <= lon <= -30:
        return "South America"
    if 35 <= lat <= 72 and -25 <= lon <= 45:
        return "Europe"
    if -35 <= lat <= 37 and -20 <= lon <= 52:
        return "Africa"
    if lat > -12 and 60 <= lon <= 150:
        return "Asia"
    if -50 <= lat <= 0 and 110 <= lon <= 180:
        return "Oceania"
    if lat < -60:
        return "Antarctica"
    if -60 <= lat <= 15 and (lon > 150 or lon < -170):
        return "Pacific Islands"
    return "Other / Ocean"


def categorize_magnitude(mag: float) -> str:
    """Bucket magnitude into human-readable risk categories."""
    if mag < 2.5:
        return "Minor"
    elif mag < 4.5:
        return "Light"
    elif mag < 6.0:
        return "Moderate"
    else:
        return "High Risk"


if __name__ == "__main__":
    df = fetch_earthquake_data()
    df = clean_data(df)
    df["risk_category"] = df["mag"].apply(categorize_magnitude)
    df["region"] = df.apply(lambda r: classify_region(r["longitude"], r["latitude"]), axis=1)
    df = df.sort_values("time").reset_index(drop=True)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False)

    print(f"Saved {len(df)} earthquake records to {OUTPUT_PATH}")
    print(df["risk_category"].value_counts())
    print(f"Date range: {df['time'].min()} to {df['time'].max()}")
