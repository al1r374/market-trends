# Market Trend

Iranian multi-market price analysis: gold, FX, equities, crypto, and funds — with a Streamlit dashboard on the Jalali calendar.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Update data

```bash
python -m market_trend.etl.update
# optional: python -m market_trend.etl.update --market Gold --market Dollar
```

When finished, the command prints a report: per-market fetch status, date ranges, upserted row count, and DB coverage. Use `--quiet` to skip the report.

After adding new markets (or if charts look stale), refresh DB + Streamlit cache and restart the app:

```bash
./scripts/refresh_dashboard.sh
# or only one market:
./scripts/refresh_dashboard.sh GoldBox
# cache clear + restart only:
./scripts/refresh_dashboard.sh --no-update
```

Then select the new markets in the sidebar (selection is sticky via URL params).

## Daily cron

`scripts/fetch_prices_daily.sh` refreshes all markets and appends output to `logs/fetch_prices.log`. Installed for 18:00 local time:

```cron
0 18 * * * /Users/alirezadp10/Projects/market-trend/scripts/fetch_prices_daily.sh
```

A sleeping Mac skips that run until it wakes.

## Run the app

```bash
streamlit run app/streamlit_app.py
```

Or open **http://markets.local/** after login (LaunchAgent + Caddy on port 80). Install/repair with:

```bash
brew install caddy   # once
bash scripts/install_market_local.sh
```

Logs: `logs/streamlit.*.log`, `logs/caddy.*.log`.

The UI uses **IRANSans-Edit** from `app/static/fonts/IRANSans-Edit.ttf` (static serving enabled in `.streamlit/config.toml`).

## Project layout

| Path | Role |
|------|------|
| `config.yaml` | Markets, colors, date range, paths |
| `market_trend/` | Config, DB, enrich, metrics, charts, ETL |
| `app/streamlit_app.py` | Interactive dashboard |
| `market_data.db` | SQLite price store |
| `events.csv` | Historical events (optional tags inferred) |
| `notebooks/explore.ipynb` | Thin research sandbox |
| `notebooks/legacy_market.ipynb` | Archived original notebook (outputs cleared) |

## Tests

```bash
pytest
```
