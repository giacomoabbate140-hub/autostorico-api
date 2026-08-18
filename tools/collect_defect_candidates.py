"""Collect one safe, reviewable batch of AutoStorico defect-source candidates.

This script never alters the public vehicle_defects.json catalog. It only stores
approved-domain search results in a review queue. Official/manufacturer sources
may generate update metadata for the app; community and independent sources stay
silent in the review queue until a human promotes a finding into the catalog.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGETS_PATH = ROOT / "data" / "defect_research_targets.json"
QUEUE_PATH = ROOT / "data" / "defect_research_queue.json"
API_URL = os.environ.get(
    "AUTOSTORICO_DEFECT_RESEARCH_URL",
    "https://autostorico-api-1.onrender.com/api/admin/defect-source-candidates",
).strip()
API_KEY = os.environ.get("AUTOSTORICO_DEFECT_RESEARCH_API_KEY", "").strip()
NOTIFIABLE_SOURCE_TYPES = {"official_candidate", "manufacturer_candidate"}


def read_json(path: Path, fallback: dict) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return data if isinstance(data, dict) else fallback


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_candidates(target: dict) -> dict:
    params = {
        "make": str(target["make"]),
        "model": str(target["model"]),
        "year": str(target.get("year") or ""),
        "engine": str(target.get("engine") or ""),
    }
    request = urllib.request.Request(
        f"{API_URL}?{urllib.parse.urlencode(params)}",
        headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"},
    )

    attempts = 4
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=75) as response:
                if response.status != 200:
                    raise RuntimeError(f"API response {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("Invalid API response")
            return payload
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            transient = isinstance(exc, urllib.error.HTTPError) and exc.code in (
                429,
                500,
                502,
                503,
                504,
            )
            transient = transient or isinstance(exc, (urllib.error.URLError, TimeoutError))
            if attempt < attempts and transient:
                print(
                    f"Tentativo {attempt} fallito ({exc}); il server potrebbe essere in "
                    "cold start, riprovo tra 25s...",
                    file=sys.stderr,
                )
                time.sleep(25)
                continue
            raise
    raise RuntimeError(f"fetch_candidates failed after {attempts} attempts") from last_error


def main() -> int:
    if not API_KEY:
        print("Missing AUTOSTORICO_DEFECT_RESEARCH_API_KEY secret.", file=sys.stderr)
        return 2
    targets = read_json(TARGETS_PATH, {"targets": []}).get("targets", [])
    if not isinstance(targets, list) or not targets:
        print("No research targets configured.", file=sys.stderr)
        return 2

    queue = read_json(
        QUEUE_PATH,
        {"schemaVersion": 1, "updatedAt": None, "cursor": 0, "candidates": []},
    )
    cursor = int(queue.get("cursor") or 0) % len(targets)
    target = targets[cursor]
    result = fetch_candidates(target)
    existing = {
        str(item.get("sourceUrl") or "")
        for item in queue.get("candidates", [])
        if isinstance(item, dict)
    }
    now = datetime.now(timezone.utc).isoformat()
    accepted = []
    for source in result.get("candidates", []):
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url or url in existing:
            continue
        accepted.append(
            {
                "status": "pending_review",
                "collectedAt": now,
                "make": target["make"],
                "model": target["model"],
                "year": target.get("year"),
                "engine": target.get("engine", ""),
                "sourceName": str(source.get("sourceName") or "Fonte da verificare"),
                "sourceType": str(source.get("sourceType") or "community_candidate"),
                "researchCategory": str(
                    source.get("researchCategory") or "official_or_technical"
                ),
                "title": str(source.get("title") or ""),
                "snippet": str(source.get("snippet") or ""),
                "sourceUrl": url,
            }
        )
    queue["schemaVersion"] = 1
    queue["updatedAt"] = now
    queue["cursor"] = (cursor + 1) % len(targets)
    queue["candidates"] = [*queue.get("candidates", []), *accepted][-1000:]

    # All approved-domain results remain available for manual review, but only
    # official authorities and vehicle manufacturers are allowed to create the
    # app-facing latestUpdate metadata. Forum/community/independent results are
    # deliberately silent so users never receive an unverified defect alert.
    notifiable = [
        candidate
        for candidate in accepted
        if candidate.get("sourceType") in NOTIFIABLE_SOURCE_TYPES
    ]
    if notifiable:
        source_labels = []
        source_urls = []
        for candidate in notifiable:
            label = str(candidate.get("sourceName") or "Fonte ufficiale").strip()
            title = str(candidate.get("title") or "").strip()
            detail = f"{label}: {title}" if title else label
            if detail not in source_labels:
                source_labels.append(detail)
            url = str(candidate.get("sourceUrl") or "").strip()
            if url and url not in source_urls:
                source_urls.append(url)
        queue["latestUpdate"] = {
            "id": now,
            "updatedAt": now,
            "addedCount": len(notifiable),
            "summary": (
                f"Trovate {len(notifiable)} nuove fonti ufficiali per "
                f"{target['make']} {target['model']}, in verifica."
            ),
            "details": source_labels[:4],
            "sources": source_urls[:4],
            "vehicles": [
                {"make": target["make"], "model": target["model"]},
            ],
        }

    write_json(QUEUE_PATH, queue)
    print(
        f"Checked {target['make']} {target['model']}; added {len(accepted)} review candidates "
        f"({len(notifiable)} official/manufacturer)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
