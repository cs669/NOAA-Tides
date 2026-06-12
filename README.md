# NOAA-Tides

A Streamlit dashboard for viewing a week of NOAA tide predictions in a polished, high-contrast interface inspired by modern tide tools.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Features

- Fetches NOAA CO-OPS tide predictions for a station id
- Searches the full NOAA tide station catalog by city, name, state, or station id
- Saves recently selected stations for quick reuse in the sidebar
- Groups forecasts into a seven day view
- Shows summary cards for the tide range and forecast count
- Styled for fast scanning on desktop and mobile

## Usage

Open the app, search for a NOAA station in the sidebar, and pick from the matching results.

## Notes

- This repository was initialized locally and pushed to GitHub; if you created the remote with a README, it was merged during the first push.

