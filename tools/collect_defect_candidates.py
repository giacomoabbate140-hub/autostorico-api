"""Collect safe, reviewable AutoStorico defect-source candidates.

The public defect catalog is never modified automatically. Results from trusted
sources are stored in a review queue. Only official authorities and vehicle
manufacturers can generate app-facing update metadata; community/independent
sources remain silent until manually reviewed.
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


def batch_size() -> int:
    try:
        value = int(os.environ.get("AUTOSTORICO_DEFECT_BATCH_SIZE", "3"))
    except ValueError:
        value = 3
    return max(1, min(5, value))


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
                delay = 20 if attempt == 1 else 30
                print(
                    f"Tentativo {attempt} fallito ({exc}); riprovo tra {delay}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(f"fetch_candidates failed after {attempts} attempts") from last_error


def normalize_candidate(source: dict, target: dict, now: str) -> dict | None:
    if not isinstance(source, dict):
        return None
    url = str(source.get("url") or "").strip()
    if not url:
        return None
    return {
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


def build_latest_update(notifiable: list[dict], now: str) -> dict:
    source_labels: list[str] = []
    source_urls: list[str] = []
    vehicles: list[dict[str, str]] = []
    seen_vehicles: set[tuple[str, str]] = set()

    for candidate in notifiable:
        label = str(candidate.get("sourceName") or "Fonte ufficiale").strip()
        title = str(candidate.get("title") or "").strip()
        detail = f"{label}: {title}" if title else label
        if detail not in source_labels:
            source_labels.append(detail)
        url = str(candidate.get("sourceUrl") or "").strip()
        if url and url not in source_urls:
            source_urls.append(url)
        make = str(candidate.get("make") or "").strip()
        model = str(candidate.get("model") or "").strip()
        key = (make.casefold(), model.casefold())
        if make and model and key not in seen_vehicles:
            seen_vehicles.add(key)
            vehicles.append({"make": make, "model": model})

    vehicle_labels = [f"{item['make']} {item['model']}" for item in vehicles[:3]]
    if vehicle_labels:
        suffix = " e altri modelli" if len(vehicles) > 3 else ""
        summary = (
            f"Trovate {len(notifiable)} nuove fonti ufficiali per "
            f"{', '.join(vehicle_labels)}{suffix}, in verifica."
        )
    else:
        summary = f"Trovate {len(notifiable)} nuove fonti ufficiali, in verifica."

    return {
        "id": now,
        "updatedAt": now,
        "addedCount": len(notifiable),
        "summary": summary,
        "details": source_labels[:6],
        "sources": source_urls[:6],
        "vehicles": vehicles[:6],
    }


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
    existing_candidates = [
        item for item in queue.get("candidates", []) if isinstance(item, dict)
    ]
    existing_urls = {
        str(item.get("sourceUrl") or "").strip()
        for item in existing_candidates
        if str(item.get("sourceUrl") or "").strip()
    }

    cursor = int(queue.get("cursor") or 0) % len(targets)
    count = min(batch_size(), len(targets))
    now = datetime.now(timezone.utc).isoformat()
    accepted_all: list[dict] = []
    successful_checks = 0
    errors: list[str] = []

    for offset in range(count):
        index = (cursor + offset) % len(targets)
        target = targets[index]
        try:
            result = fetch_candidates(target)
            successful_checks += 1
        except Exception as exc:  # keep the remaining targets useful if one provider is transiently down
            errors.append(f"{target.get('make')} {target.get('model')}: {str(exc)[:180]}")
            print(f"Research error: {errors[-1]}", file=sys.stderr)
            continue

        accepted_for_target = 0
        for source in result.get("candidates", []):
            candidate = normalize_candidate(source, target, now)
            if candidate is None:
                continue
            url = str(candidate.get("sourceUrl") or "")
            if url in existing_urls:
                continue
            existing_urls.add(url)
            accepted_all.append(candidate)
            accepted_for_target += 1

        print(
            f"Checked {target['make']} {target['model']}; "
            f"added {accepted_for_target} new review candidates."
        )
        # Avoid a burst against Render/provider APIs while still keeping a compact job.
        if offset + 1 < count:
            time.sleep(2)

    if successful_checks == 0:
        print("All defect research targets failed; queue left unchanged.", file=sys.stderr)
        return 1

    queue["schemaVersion"] = 1
    queue["updatedAt"] = now
    queue["cursor"] = (cursor + count) % len(targets)
    queue["candidates"] = [*existing_candidates, *accepted_all][-1000:]

    notifiable = [
        candidate
        for candidate in accepted_all
        if candidate.get("sourceType") in NOTIFIABLE_SOURCE_TYPES
    ]
    if notifiable:
        queue["latestUpdate"] = build_latest_update(notifiable, now)

    write_json(QUEUE_PATH, queue)
    print(
        f"Batch complete: {successful_checks}/{count} targets checked, "
        f"{len(accepted_all)} candidates added, "
        f"{len(notifiable)} official/manufacturer notifications eligible."
    )
    if errors:
        print(f"Partial errors: {len(errors)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
