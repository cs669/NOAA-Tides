# NOAA-Tides

A Streamlit dashboard and native Android app for viewing a week of NOAA tide predictions in a polished, high-contrast interface inspired by modern tide tools.

## Run Web App Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Android App

A native Android app built with **Kotlin** and **Jetpack Compose** lives in its own repo: [cs669/NOAA-Tides-Android](https://github.com/cs669/NOAA-Tides-Android).

## Features

- Fetches NOAA CO-OPS tide predictions for a station id
- Searches the full NOAA tide station catalog by city, name, state, or station id
- Saves recently selected stations for quick reuse
- Groups forecasts into a seven day view
- Interactive weekly tide curve chart with touch inspection
- Summary cards for current tide height, station info, forecast span, and update time
