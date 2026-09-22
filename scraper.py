#!/usr/bin/env python3
"""
Data scraper — config-driven, retry + backoff, structured JSON output.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

# ----------------------------- Logging -----------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper")

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
LATEST_FILE = DATA_DIR / "latest.json"
CONFIG_FILE = ROOT / "config.json"


# ----------------------------- Models ------------------------------
@dataclass
class ScrapeResult:
    source: str
    url: str
    scraped_at: str
    duration_ms: int
    count: int
    records: list[dict[str, Any]]
    ok: bool
    error: str | None = None


# --------------------------- HTTP layer ----------------------------
class Scraper:
    def __init__(self, request_cfg: dict[str, Any]):
        self.cfg = request_cfg
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.cfg.get("user_agent", "GHAScraper/1.0"),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
    )
    def fetch(self, url: str) -> str:
        log.info("GET %s", url)
        resp = self.session.get(url, timeout=self.cfg.get("timeout", 30))
        resp.raise_for_status()
        return resp.text

    def parse(self, html: str, target: dict[str, Any]) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "lxml")
        container_sel = target["container"]
        fields = target.get("fields", {})
        list_field = target.get("list_field", {})

        nodes = soup.select(container_sel)
        log.info("Found %d nodes for '%s'", len(nodes), container_sel)

        records: list[dict[str, Any]] = []
        for node in nodes:
            rec: dict[str, Any] = {}

            for key, sel in fields.items():
                el = node.select_one(sel)
                rec[key] = el.get_text(strip=True) if el else None

            for key, sel in list_field.items():
                rec[key] = [e.get_text(strip=True) for e in node.select(sel)]

            records.append(rec)

        return records

    def run(self, target: dict[str, Any]) -> ScrapeResult:
        started = time.perf_counter()
        name, url = target["name"], target["url"]

        try:
            html = self.fetch(url)
            records = self.parse(html, target)

            # base fields
            scraped_at = datetime.now(timezone.utc).isoformat()
            for r in records:
                r.setdefault("_source", name)
                r.setdefault("_scraped_at", scraped_at)

            duration = int((time.perf_counter() - started) * 1000)
            log.info("OK  %s → %d records in %dms", name, len(records), duration)

            return ScrapeResult(
                source=name, url=url, scraped_at=scraped_at,
                duration_ms=duration, count=len(records),
                records=records, ok=True,
            )

        except Exception as exc:
            duration = int((time.perf_counter() - started) * 1000)
            log.error("FAIL %s → %s", name, exc)
            return ScrapeResult(
                source=name, url=url,
                scraped_at=datetime.now(timezone.utc).isoformat(),
                duration_ms=duration, count=0,
                records=[], ok=False, error=str(exc),
            )


# ----------------------------- Output ------------------------------
def build_summary(results: list[ScrapeResult]) -> dict[str, Any]:
    total_records = sum(r.count for r in results)
    ok_count = sum(1 for r in results if r.ok)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_sources": len(results),
        "successful_sources": ok_count,
        "failed_sources": len(results) - ok_count,
        "total_records": total_records,
        "sources": [
            {
                "name": r.source,
                "url": r.url,
                "ok": r.ok,
                "count": r.count,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in results
        ],
    }


def save_output(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_DIR.mkdir(exist_ok=True)

    # latest
    LATEST_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Wrote %s", LATEST_FILE.relative_to(ROOT))

    # daily snapshot
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap = HISTORY_DIR / f"{day}.json"
    snap.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Wrote %s", snap.relative_to(ROOT))


# ------------------------------ Main -------------------------------
def main() -> int:
    if not CONFIG_FILE.exists():
        log.error("config.json not found")
        return 1

    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    scraper = Scraper(cfg.get("request", {}))
    delay = cfg.get("request", {}).get("delay_seconds", 1.0)

    results: list[ScrapeResult] = []
    for i, target in enumerate(cfg["targets"]):
        if i > 0 and delay:
            time.sleep(delay)  # politeness
        results.append(scraper.run(target))

    payload = {
        "summary": build_summary(results),
        "data": {r.source: r.records for r in results},
    }
    save_output(payload)

    failed = payload["summary"]["failed_sources"]
    log.info(
        "Done. %d/%d sources OK, %d records total",
        payload["summary"]["successful_sources"],
        payload["summary"]["total_sources"],
        payload["summary"]["total_records"],
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
