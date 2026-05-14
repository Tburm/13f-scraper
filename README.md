# SALP 13F Monitor

Polls the SEC submissions feed for **Situational Awareness LP** (`CIK0002045724`), detects new `13F-HR` filings, finds the filing's actual information-table XML, diffs it against the fixed baseline 13F supplied in the request, and sends a rich Discord alert.

Discord channel IDs and tokens are deployment configuration, not source-code defaults. Put them in `.env` or your host/container environment.

## What it does

- Polls `https://data.sec.gov/submissions/CIK0002045724.json`.
- Detects when the latest `13F-HR` accession changes.
- Resolves the actual info table XML via SEC archive `index.json`, rather than guessing the filename.
- Compares the new holdings to the fixed baseline:
  - Rendered EDGAR URL: `https://www.sec.gov/Archives/edgar/data/2045724/000204572425000002/xslForm13F_X02/SALP13fq1.xml`
  - The service automatically normalizes this to the raw XML URL before parsing.
- Reports new, sold, increased, decreased, and value-only changed positions.
- Emits simple mechanical trade-style signals such as `LONG XYZ` or `SELL XYZ` based solely on the holding diff. These are **not investment advice**.

## Configuration

Environment variables:

| Variable | Default | Notes |
| --- | --- | --- |
| `DISCORD_CHANNEL_ID` | unset | Required only with `DISCORD_BOT_TOKEN`; keep this in `.env`/deployment config. |
| `DISCORD_BOT_TOKEN` | unset | Bot token with permission to post in the alert channel. |
| `DISCORD_WEBHOOK_URL` | unset | Alternative to bot token; if set, webhook is used first. |
| `SEC_USER_AGENT` | `salp-13f-monitor/0.1 contact@example.com` | Set this to a real app/contact string for SEC fair-access compliance. |
| `POLL_SECONDS` | `300` | Poll interval. |
| `STATE_PATH` | `state/salp_13f_state.json` | Last seen filing state. |
| `BASELINE_13F_URL` | fixed URL above | Baseline filing to compare against. |
| `ALERT_ON_FIRST_RUN` | `false` | If false, first run seeds state without alerting. |

## Install and run locally with uv

```bash
uv sync

export DISCORD_CHANNEL_ID='target-channel-id'
export DISCORD_BOT_TOKEN='your-bot-token'
export SEC_USER_AGENT='salp-13f-monitor your-email@example.com'
uv run salp-13f-monitor
```

Send a synthetic test alert for the current latest filing:

```bash
uv run salp-13f-monitor --once --test-alert
```

Preview that same test alert without sending:

```bash
uv run salp-13f-monitor --once --test-alert --dry-run
```

Run once and print the payload/status without sending:

```bash
uv run salp-13f-monitor --once --dry-run --alert-on-first-run --state-path /tmp/salp-state.json
```

## Docker

```bash
docker build -t salp-13f-monitor .
docker run --rm \
  -e DISCORD_BOT_TOKEN='your-bot-token' \
  -e SEC_USER_AGENT='salp-13f-monitor your-email@example.com' \
  -v "$PWD/state:/app/state" \
  salp-13f-monitor
```

## Notes on Discord delivery

Use either:

1. `DISCORD_WEBHOOK_URL` for a channel webhook, or
2. `DISCORD_BOT_TOKEN` plus `DISCORD_CHANNEL_ID` in `.env` or deployment config.

The repo does not include secrets. Add the bot token/webhook in your deployment environment.

## Tests

```bash
uv sync --extra dev
uv run pytest
```
