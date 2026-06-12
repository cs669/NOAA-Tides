from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit.runtime import exists as streamlit_runtime_exists


BASE_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATION_CATALOG_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"
RECENT_STATIONS_FILE = Path(__file__).with_name(".recent_stations.json")
MAX_RECENT_STATIONS = 10


@dataclass(frozen=True)
class TidePoint:
    time: datetime
    value: float
    kind: str | None = None


def format_height(value: float | None) -> str:
    return "--" if value is None else f"{value:.2f} ft"


def format_clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def format_day_label(value: date) -> str:
    return value.strftime("%a, %b ") + str(value.day)


def format_station_label(station: dict[str, Any]) -> str:
    name = station.get("name") or station.get("id") or "Unknown station"
    state = station.get("state") or ""
    identifier = station.get("id") or ""

    pieces = [name]
    if state:
        pieces.append(state)
    if identifier:
        pieces.append(identifier)

    return " · ".join(pieces)


def normalize_station(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id", "")).strip(),
        "name": str(item.get("name", "")).strip(),
        "state": str(item.get("state", "")).strip(),
        "lat": item.get("lat"),
        "lng": item.get("lng"),
    }


@lru_cache(maxsize=1)
def load_station_catalog() -> list[dict[str, Any]]:
    response = requests.get(STATION_CATALOG_URL, timeout=30)
    response.raise_for_status()
    payload = response.json()
    stations = [normalize_station(item) for item in payload.get("stations", [])]
    return sorted(
        [station for station in stations if station["id"] and station["name"]],
        key=lambda station: (station["name"].lower(), station["state"].lower(), station["id"]),
    )


def search_stations(query: str, stations: list[dict[str, Any]], limit: int = 30) -> list[dict[str, Any]]:
    cleaned_query = query.strip().lower()
    if not cleaned_query:
        return stations[:limit]

    scored_results: list[tuple[int, str, dict[str, Any]]] = []
    for station in stations:
        haystack = " ".join(
            [
                station["id"].lower(),
                station["name"].lower(),
                station.get("state", "").lower(),
                str(station.get("lat", "")).lower(),
                str(station.get("lng", "")).lower(),
            ]
        )

        if cleaned_query not in haystack:
            continue

        if station["id"].lower().startswith(cleaned_query):
            score = 0
        elif station["name"].lower().startswith(cleaned_query):
            score = 1
        elif cleaned_query in station["name"].lower():
            score = 2
        else:
            score = 3

        scored_results.append((score, station["name"], station))

    return [station for _, _, station in sorted(scored_results)][:limit]


def load_recent_stations() -> list[dict[str, Any]]:
    if not RECENT_STATIONS_FILE.exists():
        return []

    try:
        payload = json.loads(RECENT_STATIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(payload, list):
        return []

    recent_stations: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            station = normalize_station(item)
            if station["id"] and station["name"]:
                recent_stations.append(station)

    return recent_stations[:MAX_RECENT_STATIONS]


def save_recent_stations(stations: list[dict[str, Any]]) -> None:
    try:
        RECENT_STATIONS_FILE.write_text(
            json.dumps(stations[:MAX_RECENT_STATIONS], indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def remember_station(station: dict[str, Any]) -> None:
    recent_stations = [item for item in load_recent_stations() if item["id"] != station["id"]]
    recent_stations.insert(0, normalize_station(station))
    save_recent_stations(recent_stations)


def parse_prediction(entry: dict[str, Any]) -> TidePoint | None:
    try:
        return TidePoint(
            time=datetime.fromisoformat(str(entry["t"])),
            value=float(entry["v"]),
            kind=str(entry.get("type")) if entry.get("type") is not None else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


def fetch_predictions(station_id: str, interval: str, start: date, end: date) -> list[TidePoint]:
    params = {
        "product": "predictions",
        "application": "NOAA Tide Dashboard",
        "begin_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
        "datum": "MLLW",
        "station": station_id,
        "time_zone": "lst_ldt",
        "units": "english",
        "interval": interval,
        "format": "json",
    }

    response = requests.get(BASE_URL, params=params, timeout=20)
    response.raise_for_status()
    payload = response.json()
    return [point for item in payload.get("predictions", []) if (point := parse_prediction(item)) is not None]


def summarize_days(hourly: list[TidePoint], events: list[TidePoint]) -> list[dict[str, Any]]:
    day_map: dict[date, dict[str, Any]] = {}

    for point in hourly:
        key = point.time.date()
        bucket = day_map.setdefault(
            key,
            {
                "date": key,
                "samples": [],
                "events": [],
                "min": None,
                "max": None,
            },
        )
        bucket["samples"].append(point)
        bucket["min"] = point if bucket["min"] is None or point.value < bucket["min"].value else bucket["min"]
        bucket["max"] = point if bucket["max"] is None or point.value > bucket["max"].value else bucket["max"]

    for point in events:
        bucket = day_map.get(point.time.date())
        if bucket is not None:
            bucket["events"].append(point)

    return [day_map[key] for key in sorted(day_map)]


@lru_cache(maxsize=8)
def load_station_data(station_id: str) -> dict[str, Any]:
    start = datetime.now().date()
    end = start + timedelta(days=6)

    hourly = fetch_predictions(station_id, "h", start, end)
    events = fetch_predictions(station_id, "hilo", start, end)
    chart_points = hourly or events
    days = summarize_days(chart_points, events)
    values = [point.value for point in chart_points]
    current = min(chart_points, key=lambda point: abs((point.time - datetime.now()).total_seconds())) if chart_points else None

    station = next(
        (item for item in load_station_catalog() if item["id"] == station_id),
        {"id": station_id, "name": station_id, "state": ""},
    )

    return {
        "station": station,
        "generated_at": datetime.now(),
        "hourly": chart_points,
        "events": events,
        "days": days,
        "min_value": min(values) if values else None,
        "max_value": max(values) if values else None,
        "current_value": current.value if current else None,
        "current_time": current.time if current else None,
    }


def inject_styles() -> None:
    st.markdown(
        """
        <style>
          .stApp {
            background:
              radial-gradient(circle at top left, rgba(56, 169, 255, 0.16), transparent 28%),
              radial-gradient(circle at top right, rgba(124, 240, 199, 0.12), transparent 22%),
              linear-gradient(180deg, #07111c 0%, #09192d 45%, #050b14 100%);
            color: #edf5fb;
          }
          section.main > div {
            padding-top: 1.1rem;
          }
          .hero {
            padding: 1.5rem 1.6rem;
            border: 1px solid rgba(255, 255, 255, 0.11);
            border-radius: 28px;
            background: linear-gradient(135deg, rgba(12, 24, 43, 0.92), rgba(7, 15, 28, 0.84));
            box-shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
          }
          .eyebrow {
            display: inline-flex;
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            border: 1px solid rgba(255, 255, 255, 0.12);
            color: #a6b4c9;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            font-size: 0.72rem;
          }
          .hero h1 {
            margin: 0.6rem 0 0.65rem;
            font-size: clamp(2.3rem, 5vw, 4.8rem);
            line-height: 0.95;
            letter-spacing: -0.06em;
          }
          .hero p {
            margin: 0;
            max-width: 68ch;
            color: #a6b4c9;
            line-height: 1.65;
          }
          .card {
            padding: 1rem 1rem 0.9rem;
            border-radius: 22px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background: linear-gradient(180deg, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0.02));
          }
          .card-label {
            color: #a6b4c9;
            font-size: 0.82rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
          }
          .card-value {
            margin-top: 0.35rem;
            font-size: 1.6rem;
            font-weight: 700;
            letter-spacing: -0.03em;
          }
          .day-grid {
            display: grid;
            grid-template-columns: repeat(7, minmax(0, 1fr));
            gap: 0.8rem;
          }
          .day {
            padding: 0.95rem;
            border-radius: 20px;
            border: 1px solid rgba(255, 255, 255, 0.08);
            background: rgba(255, 255, 255, 0.035);
            min-height: 220px;
          }
          .day h3 {
            margin: 0;
            font-size: 1rem;
          }
          .day .date {
            margin-top: 0.15rem;
            color: #a6b4c9;
            font-size: 0.88rem;
          }
          .tide-row {
            display: flex;
            justify-content: space-between;
            gap: 0.75rem;
            margin-top: 0.55rem;
            padding-top: 0.55rem;
            border-top: 1px solid rgba(255, 255, 255, 0.08);
            color: #d7e4f0;
            font-size: 0.9rem;
          }
          .tide-row span:last-child {
            color: #edf5fb;
            font-weight: 700;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def make_chart(hourly: list[TidePoint]) -> go.Figure:
    figure = go.Figure()

    if hourly:
        figure.add_trace(
            go.Scatter(
                x=[point.time for point in hourly],
                y=[point.value for point in hourly],
                mode="lines",
                line={"color": "#76d0ff", "width": 3},
                fill="tozeroy",
                fillcolor="rgba(118, 208, 255, 0.16)",
                hovertemplate="%{x|%a %b %d, %I:%M %p}<br>%{y:.2f} ft<extra></extra>",
            )
        )

    figure.update_layout(
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=420,
        xaxis={"showgrid": False, "showline": False, "zeroline": False, "tickfont": {"color": "#a6b4c9"}},
        yaxis={"showgrid": True, "gridcolor": "rgba(255,255,255,0.08)", "tickfont": {"color": "#a6b4c9"}},
        showlegend=False,
    )
    return figure


def render_day_cards(days: list[dict[str, Any]]) -> None:
    columns = st.columns(7)
    for column, day in zip(columns, days, strict=False):
        with column:
            st.markdown(
                f"""
                <div class="day">
                  <h3>{format_day_label(day["date"])} </h3>
                  <div class="date">{len(day["events"])} tide events</div>
                  <div class="tide-row"><span>High</span><span>{format_height(day["max"].value if day["max"] else None)}</span></div>
                  <div class="tide-row"><span>Low</span><span>{format_height(day["min"].value if day["min"] else None)}</span></div>
                  {"".join(
                    f'<div class="tide-row"><span>{point.kind or "Tide"} {format_clock(point.time)}</span><span>{format_height(point.value)}</span></div>'
                    for point in day["events"][:2]
                  )}
                </div>
                """,
                unsafe_allow_html=True,
            )


def main() -> None:
    if not streamlit_runtime_exists():
        print("Run this app with: streamlit run app.py")
        return

    st.set_page_config(page_title="NOAA Tide Week View", page_icon="🌊", layout="wide")
    inject_styles()

    catalog = load_station_catalog()
    recent_stations = load_recent_stations()

    if not catalog:
        st.error("Unable to load the NOAA station catalog. Check your network connection and try again.")
        return

    st.markdown(
        """
        <div class="hero">
          <div class="eyebrow">NOAA tide week view</div>
          <h1>Seven days of tide data.</h1>
          <p>
            dashboard.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.header("Find a station")
    search_query = st.sidebar.text_input(
        "Search NOAA stations",
        placeholder="City, station name, state, or station id",
        key="station_search_query",
    )

    if search_query.strip():
        visible_stations = search_stations(search_query, catalog)
        if not visible_stations:
            st.sidebar.warning("No matching stations yet. Try a shorter city name or a station id.")
            visible_stations = recent_stations or catalog[:25]
    else:
        visible_stations = recent_stations or catalog[:25]

    station_map = {station["id"]: station for station in visible_stations}
    if not station_map:
        st.error("No stations are available to display right now.")
        return

    default_station_id = st.session_state.get("selected_station_id")
    if default_station_id not in station_map:
        default_station_id = next(iter(station_map))

    selected_station_id = st.sidebar.selectbox(
        "Station",
        options=list(station_map.keys()),
        index=list(station_map.keys()).index(default_station_id),
        format_func=lambda station_id: format_station_label(station_map[station_id]),
        key="station_picker",
    )

    st.session_state["selected_station_id"] = selected_station_id
    selected_station = station_map[selected_station_id]
    remember_station(selected_station)

    data = load_station_data(selected_station_id)

    top = st.columns(4)
    top[0].markdown(
        f'<div class="card"><div class="card-label">Current tide height</div><div class="card-value">{format_height(data["current_value"])}</div></div>',
        unsafe_allow_html=True,
    )
    top[1].markdown(
        f'<div class="card"><div class="card-label">Station</div><div class="card-value">{data["station"]["name"]}</div></div>',
        unsafe_allow_html=True,
    )
    top[2].markdown(
        f'<div class="card"><div class="card-label">Forecast span</div><div class="card-value">7 days</div></div>',
        unsafe_allow_html=True,
    )
    top[3].markdown(
        f'<div class="card"><div class="card-label">Updated</div><div class="card-value">{data["generated_at"].strftime("%b %d, %I:%M %p")}</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("### Weekly tide curve")
    st.plotly_chart(make_chart(data["hourly"]), width="stretch")

    st.markdown("### Daily breakdown")
    render_day_cards(data["days"])

    st.markdown(
        f"""
        <p style="color: #a6b4c9; margin-top: 1rem; line-height: 1.65;">
          NOAA predictions for station <strong>{data["station"]["id"]}</strong> in {data["station"].get("state", "") or "the NOAA catalog"}.
          Data source: NOAA CO-OPS predictions API.
        </p>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
