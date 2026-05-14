from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

import requests

SEC_CIK = "0002045724"
SEC_CIK_INT = "2045724"
SUBMISSIONS_URL = f"https://data.sec.gov/submissions/CIK{SEC_CIK}.json"
DEFAULT_BASELINE_URL = "https://www.sec.gov/Archives/edgar/data/2045724/000204572425000002/xslForm13F_X02/SALP13fq1.xml"
DEFAULT_STATE_PATH = Path("state/salp_13f_state.json")
LOG = logging.getLogger("salp_13f_monitor")

# Best-effort issuer-name to ticker overrides for concise alert signals. 13F XML
# exposes CUSIP, not ticker, so unknown issuers gracefully fall back to a compact
# issuer token.
SYMBOL_OVERRIDES = {
    "INTEL": "INTC",
    "BLOOM ENERGY": "BE",
    "COREWEAVE": "CRWV",
    "LUMENTUM": "LITE",
    "CORE SCIENTIFIC": "CORZ",
    "IREN": "IREN",
    "APPLIED DIGITAL": "APLD",
    "OKLO": "OKLO",
    "ROCKET LAB": "RKLB",
    "AST SPACEMOBILE": "ASTS",
    "RECURSION": "RXRX",
    "IONQ": "IONQ",
    "RIGETTI": "RGTI",
    "JOBY": "JOBY",
    "ARCHER AVIATION": "ACHR",
    "VERTIV": "VRT",
    "TESLA": "TSLA",
    "NVIDIA": "NVDA",
    "ADVANCED MICRO": "AMD",
}


@dataclass(frozen=True)
class Filing:
    accession: str
    filing_date: str
    report_date: str | None
    primary_document: str | None
    info_table_url: str
    index_url: str


@dataclass(frozen=True)
class Holding:
    name: str
    cusip: str
    value_usd: int
    shares: int
    put_call: str | None = None

    @property
    def key(self) -> str:
        # CUSIP is the SEC 13F stable identifier; include option type to avoid
        # mixing equity and option positions if present.
        return f"{self.cusip}|{self.put_call or ''}"


@dataclass(frozen=True)
class HoldingChange:
    kind: str
    name: str
    cusip: str
    old_value_usd: int
    new_value_usd: int
    old_shares: int
    new_shares: int
    value_delta_usd: int
    share_delta: int
    pct_share_delta: float | None
    signal: str


class SecClient:
    def __init__(self, user_agent: str, timeout: int = 30) -> None:
        if not user_agent or "example" in user_agent.lower():
            LOG.warning("Set SEC_USER_AGENT to a real app/contact string for SEC fair-access compliance.")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Accept": "application/json,text/xml,*/*"})
        self.timeout = timeout

    def get_json(self, url: str) -> dict[str, Any]:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_text(self, url: str) -> str:
        response = self.session.get(normalize_sec_xml_url(url), timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def latest_13f(self) -> Filing:
        submissions = self.get_json(SUBMISSIONS_URL)
        recent = submissions["filings"]["recent"]
        for i, form in enumerate(recent["form"]):
            if form.startswith("13F-HR"):
                accession = recent["accessionNumber"][i]
                return self.resolve_info_table(
                    accession=accession,
                    filing_date=recent["filingDate"][i],
                    report_date=recent.get("reportDate", [None])[i] if i < len(recent.get("reportDate", [])) else None,
                    primary_document=recent.get("primaryDocument", [None])[i] if i < len(recent.get("primaryDocument", [])) else None,
                )
        raise RuntimeError("No 13F-HR filing found in SEC submissions feed")

    def resolve_info_table(self, accession: str, filing_date: str, report_date: str | None = None, primary_document: str | None = None) -> Filing:
        compact_accession = accession.replace("-", "")
        base = f"https://www.sec.gov/Archives/edgar/data/{SEC_CIK_INT}/{compact_accession}"
        index_url = f"{base}/index.json"
        index = self.get_json(index_url)
        items = index["directory"]["item"]

        # SEC 13F information tables are usually sibling XML files. Exclude the
        # cover page and index artifacts. Prefer obvious 13F/SALP names, then any
        # remaining XML document.
        xml_names = [item["name"] for item in items if item["name"].lower().endswith(".xml")]
        candidates = [n for n in xml_names if n.lower() != "primary_doc.xml"]
        preferred = [n for n in candidates if "13f" in n.lower() or "infotable" in n.lower() or "salp" in n.lower()]
        if not preferred and candidates:
            preferred = candidates
        if not preferred:
            raise RuntimeError(f"Could not find an information-table XML in {index_url}: {xml_names}")

        return Filing(
            accession=accession,
            filing_date=filing_date,
            report_date=report_date,
            primary_document=primary_document,
            info_table_url=f"{base}/{preferred[0]}",
            index_url=index_url,
        )


def normalize_sec_xml_url(url: str) -> str:
    """Convert SEC's rendered XSL URL form to the raw archive XML URL.

    The user-facing EDGAR link often inserts an /xslForm.../ path segment that
    returns transformed HTML. The raw XML lives beside it one directory up.
    """
    parts = url.split("/")
    return "/".join(part for part in parts if not part.startswith("xslForm"))


def _text(node: ET.Element, local_name: str) -> str | None:
    for child in node.iter():
        if child.tag.split("}")[-1] == local_name and child.text is not None:
            return child.text.strip()
    return None


def _int_text(node: ET.Element, local_name: str) -> int:
    value = _text(node, local_name)
    if not value:
        return 0
    return int(value.replace(",", ""))


def parse_13f_xml(xml_text: str) -> dict[str, Holding]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    holdings: dict[str, Holding] = {}
    for info in root.iter():
        if info.tag.split("}")[-1] != "infoTable":
            continue
        holding = Holding(
            name=_text(info, "nameOfIssuer") or "UNKNOWN",
            cusip=(_text(info, "cusip") or "UNKNOWN").upper(),
            value_usd=_int_text(info, "value"),  # SALP's XML reports dollar values directly.
            shares=_int_text(info, "sshPrnamt"),
            put_call=_text(info, "putCall"),
        )
        holdings[holding.key] = holding
    return holdings


def signal_symbol(name: str) -> str:
    upper = name.upper()
    for prefix, symbol in SYMBOL_OVERRIDES.items():
        if upper.startswith(prefix):
            return symbol
    return name.split()[0].replace(".", "").replace(",", "")[:8].upper()


def classify_signal(kind: str, name: str, share_delta: int) -> str:
    symbol = signal_symbol(name)
    if kind == "new" or (kind == "increased" and share_delta > 0):
        return f"LONG {symbol}"
    if kind == "sold" or (kind == "decreased" and share_delta < 0):
        return f"SELL {symbol}"
    return f"WATCH {symbol}"


def diff_holdings(old: dict[str, Holding], new: dict[str, Holding]) -> list[HoldingChange]:
    changes: list[HoldingChange] = []
    for key in sorted(set(old) | set(new)):
        old_h = old.get(key)
        new_h = new.get(key)
        if old_h and not new_h:
            kind = "sold"
            name, cusip = old_h.name, old_h.cusip
            old_value, new_value = old_h.value_usd, 0
            old_shares, new_shares = old_h.shares, 0
        elif new_h and not old_h:
            kind = "new"
            name, cusip = new_h.name, new_h.cusip
            old_value, new_value = 0, new_h.value_usd
            old_shares, new_shares = 0, new_h.shares
        else:
            assert old_h is not None and new_h is not None
            if old_h.shares == new_h.shares and old_h.value_usd == new_h.value_usd:
                continue
            if new_h.shares > old_h.shares:
                kind = "increased"
            elif new_h.shares < old_h.shares:
                kind = "decreased"
            else:
                kind = "value_changed"
            name, cusip = new_h.name, new_h.cusip
            old_value, new_value = old_h.value_usd, new_h.value_usd
            old_shares, new_shares = old_h.shares, new_h.shares

        share_delta = new_shares - old_shares
        pct = None if old_shares == 0 else (share_delta / old_shares) * 100
        changes.append(
            HoldingChange(
                kind=kind,
                name=name,
                cusip=cusip,
                old_value_usd=old_value,
                new_value_usd=new_value,
                old_shares=old_shares,
                new_shares=new_shares,
                value_delta_usd=new_value - old_value,
                share_delta=share_delta,
                pct_share_delta=pct,
                signal=classify_signal(kind, name, share_delta),
            )
        )
    return sorted(changes, key=lambda c: abs(c.value_delta_usd), reverse=True)


def money(value: int) -> str:
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.1f}K"
    return f"{sign}${value}"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def format_change(change: HoldingChange) -> str:
    return (
        f"**{change.kind.upper()}** {change.name} (`{change.cusip}`): "
        f"{change.old_shares:,}→{change.new_shares:,} sh ({change.share_delta:+,}, {pct(change.pct_share_delta)}), "
        f"{money(change.old_value_usd)}→{money(change.new_value_usd)} ({money(change.value_delta_usd)}). "
        f"`{change.signal}`"
    )


def build_discord_payload(filing: Filing, baseline_url: str, changes: list[HoldingChange], old_count: int, new_count: int) -> dict[str, Any]:
    top = changes[:8]
    summary_counts: dict[str, int] = {}
    for change in changes:
        summary_counts[change.kind] = summary_counts.get(change.kind, 0) + 1
    description = (
        f"New 13F-HR detected for Situational Awareness LP.\n"
        f"Accession: `{filing.accession}`\n"
        f"Filed: `{filing.filing_date}` | Report period: `{filing.report_date or 'unknown'}`\n"
        f"Compared against fixed baseline: {baseline_url}"
    )
    fields = [
        {"name": "Info table", "value": filing.info_table_url, "inline": False},
        {"name": "Change summary", "value": ", ".join(f"{k}: {v}" for k, v in sorted(summary_counts.items())) or "No holding changes", "inline": False},
        {"name": "Position counts", "value": f"Baseline: {old_count} | New: {new_count}", "inline": True},
    ]
    if top:
        lines: list[str] = []
        for change in top:
            line = format_change(change)
            if len("\n".join(lines + [line])) > 1000:
                break
            lines.append(line)
        fields.append({"name": "Top changes by value delta", "value": "\n".join(lines), "inline": False})
        fields.append({"name": "Trade-style signals (heuristic, not financial advice)", "value": ", ".join(f"`{c.signal}`" for c in top)[:1024], "inline": False})
    else:
        fields.append({"name": "Diff", "value": "No differences found versus baseline.", "inline": False})
    return {
        "content": f"13F update detected: {filing.accession}",
        "embeds": [
            {
                "title": "Situational Awareness LP 13F update",
                "url": filing.info_table_url,
                "description": description[:4096],
                "color": 0x2ECC71,
                "fields": fields,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "footer": {"text": "Signals are mechanical diffs vs baseline, not investment advice."},
            }
        ],
    }


def send_discord(payload: dict[str, Any], webhook_url: str | None, bot_token: str | None, channel_id: str) -> None:
    if webhook_url:
        response = requests.post(webhook_url, json=payload, timeout=30)
    elif bot_token:
        if not channel_id:
            raise RuntimeError("Set DISCORD_CHANNEL_ID when using DISCORD_BOT_TOKEN")
        response = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
    else:
        raise RuntimeError("Set DISCORD_WEBHOOK_URL or DISCORD_BOT_TOKEN to send alerts")
    if response.status_code not in (200, 204):
        raise RuntimeError(f"Discord alert failed: HTTP {response.status_code}: {response.text}")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def build_current_payload(client: SecClient, args: argparse.Namespace, latest: Filing) -> tuple[dict[str, Any], int]:
    baseline_xml = client.get_text(args.baseline_url)
    latest_xml = client.get_text(latest.info_table_url)
    baseline_holdings = parse_13f_xml(baseline_xml)
    latest_holdings = parse_13f_xml(latest_xml)
    changes = diff_holdings(baseline_holdings, latest_holdings)
    payload = build_discord_payload(latest, args.baseline_url, changes, len(baseline_holdings), len(latest_holdings))
    return payload, len(changes)


def run_once(args: argparse.Namespace) -> bool:
    client = SecClient(user_agent=args.sec_user_agent)
    state = load_state(args.state_path)
    latest = client.latest_13f()
    LOG.info("Latest 13F: %s %s", latest.accession, latest.info_table_url)

    if args.test_alert:
        payload, change_count = build_current_payload(client, args, latest)
        payload["content"] = f"TEST ALERT - {payload['content']}"
        payload["embeds"][0]["title"] = f"TEST - {payload['embeds'][0]['title']}"
        payload["embeds"][0]["color"] = 0xF1C40F
        if args.dry_run:
            print(json.dumps(payload, indent=2))
        else:
            send_discord(payload, args.discord_webhook_url, args.discord_bot_token, args.discord_channel_id)
        LOG.info("Sent test alert for %s with %d changes", latest.accession, change_count)
        return True

    last_seen = state.get("last_accession")
    is_new = latest.accession != last_seen
    should_alert = is_new and (last_seen is not None or args.alert_on_first_run)

    if should_alert:
        payload, change_count = build_current_payload(client, args, latest)
        if args.dry_run:
            print(json.dumps(payload, indent=2))
        else:
            send_discord(payload, args.discord_webhook_url, args.discord_bot_token, args.discord_channel_id)
        LOG.info("Alerted on %s with %d changes", latest.accession, change_count)
    elif args.dry_run:
        print(json.dumps({"latest": asdict(latest), "last_seen": last_seen, "would_alert": should_alert}, indent=2))

    if is_new:
        save_state(
            args.state_path,
            {
                "last_accession": latest.accession,
                "last_filing_date": latest.filing_date,
                "last_info_table_url": latest.info_table_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return should_alert


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll SEC for SALP 13F updates and alert Discord.")
    parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("POLL_SECONDS", "300")))
    parser.add_argument("--once", action="store_true", help="Run a single poll and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print payload/status instead of sending Discord.")
    parser.add_argument("--test-alert", action="store_true", help="Send a test alert for the current latest filing regardless of saved state; does not update state.")
    parser.add_argument("--alert-on-first-run", action="store_true", default=os.getenv("ALERT_ON_FIRST_RUN", "false").lower() == "true")
    parser.add_argument("--state-path", type=Path, default=Path(os.getenv("STATE_PATH", str(DEFAULT_STATE_PATH))))
    parser.add_argument("--baseline-url", default=os.getenv("BASELINE_13F_URL", DEFAULT_BASELINE_URL))
    parser.add_argument("--discord-channel-id", default=os.getenv("DISCORD_CHANNEL_ID"))
    parser.add_argument("--discord-webhook-url", default=os.getenv("DISCORD_WEBHOOK_URL"))
    parser.add_argument("--discord-bot-token", default=os.getenv("DISCORD_BOT_TOKEN"))
    parser.add_argument("--sec-user-agent", default=os.getenv("SEC_USER_AGENT", "salp-13f-monitor/0.1 contact@example.com"))
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            run_once(args)
        except Exception:
            LOG.exception("Poll failed")
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
