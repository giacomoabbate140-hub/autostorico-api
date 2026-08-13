from __future__ import annotations

import base64
import hmac
import json
import math
import os
from pathlib import Path
import re
import html
import hashlib
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

try:
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
except ImportError:
    AuthorizedSession = None
    service_account = None


# A mobile app cannot keep a shared API secret confidential. Requests are
# therefore protected by server-side limits and cache instead of a key in APKs.
API_KEY = os.environ.get("AUTOSTORICO_API_KEY", "").strip()
HOST = os.environ.get("AUTOSTORICO_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("AUTOSTORICO_API_PORT", "8088"))
GOOGLE_CSE_API_KEY = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID", "").strip()
GOOGLE_CSE_ENABLED = os.environ.get("AUTOSTORICO_GOOGLE_CSE_ENABLED", "0") == "1"
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "").strip()
DEFECT_RESEARCH_API_KEY = os.environ.get(
    "AUTOSTORICO_DEFECT_RESEARCH_API_KEY", ""
).strip()
DEFECT_RESEARCH_ENABLED = (
    os.environ.get("AUTOSTORICO_DEFECT_RESEARCH_ENABLED", "0") == "1"
)
MARKET_SEARCH_ENABLED = os.environ.get("AUTOSTORICO_MARKET_SEARCH", "1") != "0"
MINIMUM_MARKET_LISTINGS = 3
MARKET_CACHE_TTL_SECONDS = int(os.environ.get("AUTOSTORICO_CACHE_TTL_SECONDS", str(30 * 24 * 60 * 60)))
MARKET_RATE_WINDOW_SECONDS = int(os.environ.get("AUTOSTORICO_RATE_WINDOW_SECONDS", "3600"))
MARKET_RATE_LIMIT = int(os.environ.get("AUTOSTORICO_RATE_LIMIT", "12"))
MARKET_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
MARKET_REQUESTS: dict[str, list[float]] = {}
PREMIUM_VERIFY_REQUESTS: dict[str, list[float]] = {}
DEFECT_ENTITLEMENT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
MARKET_GUARD_LOCK = threading.Lock()
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON = os.environ.get(
    "GOOGLE_PLAY_SERVICE_ACCOUNT_JSON", ""
).strip()
GOOGLE_PLAY_SERVICE_ACCOUNT_FILE = os.environ.get(
    "GOOGLE_PLAY_SERVICE_ACCOUNT_FILE", "/etc/secrets/google-play-publisher.json"
).strip()
GOOGLE_PLAY_PACKAGE_NAME = os.environ.get(
    "GOOGLE_PLAY_PACKAGE_NAME", "autostorico.myapp"
).strip()
GOOGLE_PLAY_SUBSCRIPTION_ID = os.environ.get(
    "GOOGLE_PLAY_SUBSCRIPTION_ID", "premium_6_mesi"
).strip()
GOOGLE_PLAY_DEFECTS_GOLD_PRODUCT_ID = os.environ.get(
    "GOOGLE_PLAY_DEFECTS_GOLD_PRODUCT_ID", "premium_gold_6_mesi"
).strip()
PREMIUM_API_KEY = os.environ.get("AUTOSTORICO_PREMIUM_API_KEY", "").strip()
DEVELOPER_DEVICE_ID_HASH = os.environ.get(
    "AUTOSTORICO_DEVELOPER_DEVICE_ID_HASH", ""
).strip().lower()
PREMIUM_VERIFY_RATE_LIMIT = int(os.environ.get("AUTOSTORICO_PREMIUM_VERIFY_RATE_LIMIT", "12"))
PLAY_INTEGRITY_REQUIRED = os.environ.get("AUTOSTORICO_PLAY_INTEGRITY_REQUIRED", "0") == "1"
PLAY_INTEGRITY_MIN_VERSION_CODE = int(
    os.environ.get("AUTOSTORICO_PLAY_INTEGRITY_MIN_VERSION_CODE", "31")
)
PLAY_INTEGRITY_MAX_TOKEN_AGE_SECONDS = int(
    os.environ.get("AUTOSTORICO_PLAY_INTEGRITY_MAX_TOKEN_AGE_SECONDS", "180")
)
PLAY_INTEGRITY_SEEN: dict[str, float] = {}
PLAY_INTEGRITY_LOCK = threading.Lock()
DEFECT_CATALOG_PATH = Path(__file__).parent / "data" / "vehicle_defects.json"
DEFECT_RESEARCH_QUEUE_PATH = Path(__file__).parent / "data" / "defect_research_queue.json"
DEFECT_RESEARCH_CACHE_TTL_SECONDS = int(
    os.environ.get("AUTOSTORICO_DEFECT_CACHE_TTL_SECONDS", str(30 * 24 * 60 * 60))
)
DEFECT_ENTITLEMENT_CACHE_TTL_SECONDS = int(
    os.environ.get("AUTOSTORICO_DEFECT_ENTITLEMENT_CACHE_SECONDS", "900")
)
DEFECT_RESEARCH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
DEFECT_RESEARCH_LOCK = threading.Lock()
MARKET_SITES = [
    ("AutoScout24", "autoscout24.it"),
    ("Subito Motori", "subito.it"),
    ("Automobile.it", "automobile.it"),
    ("Quattroruote", "quattroruote.it"),
    ("AutoUncle", "autouncle.it"),
    ("Trovit Auto", "auto.trovit.it"),
    ("Bakeca Motori", "bakeca.it"),
    ("AutoXY", "autoxy.it"),
    ("AutoHero", "autohero.com"),
    ("Spoticar", "spoticar.it"),
    ("AutoSuperMarket", "autosupermarket.it"),
    ("Annunci AlVolante", "annunci.alvolante.it"),
    ("Moto.it/Automoto", "automoto.it"),
]

DIRECT_MARKET_DOMAINS = [
    "autoscout24.it",
    "subito.it",
    "automobile.it",
    "autohero.com",
    "spoticar.it",
    "annunci.alvolante.it",
]

REFERENCE_MARKET_DOMAINS = [
    "quattroruote.it",
    "autouncle.it",
    "auto.trovit.it",
    "bakeca.it",
    "autoxy.it",
    "autosupermarket.it",
    "automoto.it",
]

DEFECT_RESEARCH_SOURCES = {
    "mit.gov.it": ("Ministero delle infrastrutture e dei trasporti", "official_candidate"),
    "ec.europa.eu": ("Commissione europea", "official_candidate"),
    "nhtsa.gov": ("NHTSA", "official_candidate"),
    "peugeot.it": ("Peugeot Italia", "manufacturer_candidate"),
    "citroen.it": ("Citroen Italia", "manufacturer_candidate"),
    "dacia.it": ("Dacia Italia", "manufacturer_candidate"),
    "alfaromeo.it": ("Alfa Romeo Italia", "manufacturer_candidate"),
    "fiat.it": ("Fiat Italia", "manufacturer_candidate"),
    "lancia.it": ("Lancia Italia", "manufacturer_candidate"),
    "aftersales.fiat.com": ("Documentazione ufficiale Stellantis", "manufacturer_candidate"),
    "stellantis.com": ("Stellantis", "manufacturer_candidate"),
    "forum.quattroruote.it": ("Forum Quattroruote", "community_candidate"),
    "forum-auto.caradisiac.com": ("Forum Auto Caradisiac", "community_candidate"),
    "forum-auto.com": ("Forum Auto", "community_candidate"),
    "forum.clubalfa.it": ("ClubAlfa", "community_candidate"),
    "forum.alfavirtualclub.it": ("AlfaVirtualClub", "community_candidate"),
    "fiatforum.com": ("FIAT Forum", "community_candidate"),
    "bmwpassion.com": ("BMW Passion Forum", "community_candidate"),
    "forum-bmw.fr": ("Forum BMW", "community_candidate"),
    "forum-peugeot.com": ("Forum Peugeot", "community_candidate"),
    "forumpassionepeugeot.it": ("Passione Peugeot Auto Club Italia", "community_candidate"),
    "citroen-club.it": ("Citroën-Club Italia", "community_candidate"),
    "forum-audi.com": ("Forum Audi", "community_candidate"),
    "audiownersclub.com": ("Audi Owners Club", "community_candidate"),
    "seatforum.de": ("SEAT Forum", "community_candidate"),
    "mercedesbenzclub.it": ("Mercedes-Benz Club Italia", "community_candidate"),
    "communaute.dacia.fr": ("Comunita Dacia", "community_candidate"),
    "audirsclub.it": ("Audi RS Club Italia", "community_candidate"),
    "renault.it": ("Renault Italia", "manufacturer_candidate"),
    "volkswagen.it": ("Volkswagen Italia", "manufacturer_candidate"),
    "audi.it": ("Audi Italia", "manufacturer_candidate"),
    "bmw.it": ("BMW Italia", "manufacturer_candidate"),
    "mercedes-benz.it": ("Mercedes-Benz Italia", "manufacturer_candidate"),
    "ford.it": ("Ford Italia", "manufacturer_candidate"),
    "toyota.it": ("Toyota Italia", "manufacturer_candidate"),
    "nissan.it": ("Nissan Italia", "manufacturer_candidate"),
    "kia.com": ("Kia", "manufacturer_candidate"),
    "hyundai.com": ("Hyundai", "manufacturer_candidate"),
    "skoda-auto.it": ("Skoda Italia", "manufacturer_candidate"),
    "volvocars.com": ("Volvo Cars", "manufacturer_candidate"),
    "fordclub.it": ("Ford Club Italia", "community_candidate"),
    "vwgolfcommunity.com": ("VW Golf Community", "community_candidate"),
    "hyundai-club.eu": ("Hyundai Club", "community_candidate"),
    "lrukforums.com": ("Land Rover UK Forums", "community_candidate"),
    "landroverforums.com": ("Land Rover Forums", "community_candidate"),
    "babyrr.com": ("Baby Range Rover Forum", "community_candidate"),
    "whatcar.com": ("What Car? Reliability Survey", "independent_candidate"),
    "adac.de": ("ADAC Pannenstatistik", "independent_candidate"),
}


def normalize_catalog_text(value: Any) -> str:
    """Normalize values used to match make and model without storing VIN data."""
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def canonical_catalog_make(value: Any) -> str:
    """Resolve common marque variants used by OCR and vehicle registrations."""
    normalized = normalize_catalog_text(value).replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return {
        "landrover": "land rover",
        "range rover": "land rover",
        "range rover land rover": "land rover",
    }.get(normalized, normalized)


def load_vehicle_defect_catalog() -> dict[str, Any]:
    try:
        catalog = json.loads(DEFECT_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"catalogVersion": 1, "vehicles": []}
    return catalog if isinstance(catalog, dict) else {"catalogVersion": 1, "vehicles": []}


VEHICLE_DEFECT_CATALOG = load_vehicle_defect_catalog()


def defect_research_update_status() -> dict[str, Any]:
    """Expose safe metadata for new source candidates awaiting review."""
    try:
        queue = json.loads(DEFECT_RESEARCH_QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        queue = {}
    candidates = queue.get("candidates") if isinstance(queue, dict) else []
    pending = [
        item
        for item in candidates
        if isinstance(item, dict) and item.get("status") == "pending_review"
    ] if isinstance(candidates, list) else []
    recent = pending[-3:]
    vehicles = [
        {
            "make": str(item.get("make") or "").strip(),
            "model": str(item.get("model") or "").strip(),
        }
        for item in recent
    ]
    updated_at = str(queue.get("updatedAt") or "").strip() if isinstance(queue, dict) else ""
    return {
        "id": updated_at,
        "updatedAt": updated_at,
        "pendingCount": len(pending),
        "vehicles": vehicles,
    }


def catalog_update_status() -> dict[str, Any]:
    """Expose only the public metadata used by clients to detect catalog updates."""
    latest = VEHICLE_DEFECT_CATALOG.get("latestUpdate")
    latest = latest if isinstance(latest, dict) else {}
    vehicles = latest.get("vehicles")
    safe_vehicles = [
        {
            "make": str(vehicle.get("make") or "").strip(),
            "model": str(vehicle.get("model") or "").strip(),
        }
        for vehicle in vehicles if isinstance(vehicle, dict)
    ] if isinstance(vehicles, list) else []
    return {
        "catalogVersion": catalog_year_value(VEHICLE_DEFECT_CATALOG.get("catalogVersion")),
        "updatedAt": str(VEHICLE_DEFECT_CATALOG.get("updatedAt") or "").strip(),
        "latestUpdate": {
            "id": str(latest.get("id") or "").strip(),
            "summary": str(latest.get("summary") or "").strip(),
            "vehicles": safe_vehicles,
        },
        "researchUpdate": defect_research_update_status(),
    }


def catalog_year_matches(entry: dict[str, Any], year: int | None) -> bool:
    """Match explicit bounds or a curated generation range when available."""
    if year is None:
        return True
    from_year, to_year = catalog_year_bounds(entry)
    return (not from_year or year >= from_year) and (not to_year or year <= to_year)


def catalog_year_value(value: Any) -> int:
    try:
        return max(0, int(str(value or "").strip()))
    except (TypeError, ValueError):
        return 0


def catalog_year_bounds(entry: dict[str, Any]) -> tuple[int, int]:
    """Read the generation range already present in the curated catalog."""
    from_year = catalog_year_value(entry.get("fromYear"))
    to_year = catalog_year_value(entry.get("toYear"))
    if from_year or to_year:
        return from_year, to_year

    years_label = str(entry.get("years") or "")
    range_match = re.search(
        r"\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2}|oggi)",
        years_label,
        flags=re.IGNORECASE,
    )
    if not range_match:
        return 0, 0
    from_year = catalog_year_value(range_match.group(1))
    end = range_match.group(2).casefold()
    return from_year, 0 if end == "oggi" else catalog_year_value(end)


def catalog_engine_matches(entry: dict[str, Any], engine: str) -> bool:
    keywords = entry.get("engineKeywords")
    if not isinstance(keywords, list) or not keywords:
        return True
    wanted_engine = normalize_catalog_text(engine)
    if not wanted_engine:
        return True
    return any(
        normalize_catalog_text(keyword) in wanted_engine
        for keyword in keywords
        if isinstance(keyword, str) and normalize_catalog_text(keyword)
    )


def vehicle_defect_reports(
    make: str,
    model: str,
    year: int | None = None,
    engine: str = "",
) -> dict[str, Any] | None:
    wanted_make = canonical_catalog_make(make)
    wanted_model = normalize_catalog_text(model)
    if not wanted_make or not wanted_model:
        return None

    matching_vehicles = [
        vehicle
        for vehicle in VEHICLE_DEFECT_CATALOG.get("vehicles", [])
        if canonical_catalog_make(vehicle.get("make")) == wanted_make
        and (
            normalize_catalog_text(vehicle.get("model")) == wanted_model
            or wanted_model
            in {
                normalize_catalog_text(alias)
                for alias in vehicle.get("aliases", [])
                if isinstance(alias, str)
            }
        )
        and catalog_year_matches(vehicle, year)
    ]
    matching_engine_families = [
        family
        for family in VEHICLE_DEFECT_CATALOG.get("engineFamilies", [])
        if isinstance(family, dict)
        and canonical_catalog_make(family.get("make")) == wanted_make
        and wanted_model
        in {
            normalize_catalog_text(item)
            for item in family.get("models", [])
            if isinstance(item, str)
        }
        and catalog_year_matches(family, year)
        and catalog_engine_matches(family, engine)
    ]
    if not matching_vehicles and not matching_engine_families:
        return None

    reports = [
        report
        for vehicle in matching_vehicles
        for report in vehicle.get("reports", [])
        if isinstance(report, dict)
        and catalog_year_matches(report, year)
        and catalog_engine_matches(report, engine)
    ]
    reports.extend(
        report
        for family in matching_engine_families
        for report in family.get("reports", [])
        if isinstance(report, dict)
        and catalog_year_matches(report, year)
        and catalog_engine_matches(report, engine)
    )
    return {
        "catalogVersion": VEHICLE_DEFECT_CATALOG.get("catalogVersion", 1),
        "make": matching_vehicles[0].get("make") if matching_vehicles else make.strip(),
        "model": matching_vehicles[0].get("model") if matching_vehicles else model.strip(),
        "searchContext": {"year": year, "engine": engine.strip()},
        "vehicles": matching_vehicles,
        "reports": reports,
        "disclaimer": (
            "Le segnalazioni community non sono diagnosi o richiami ufficiali. "
            "Verifica sempre VIN, manutenzione e campagne attive presso il costruttore."
        ),
    }


def defect_research_configured() -> bool:
    return bool(
        DEFECT_RESEARCH_ENABLED and DEFECT_RESEARCH_API_KEY and BRAVE_SEARCH_API_KEY
    )


def defect_research_cache_key(make: str, model: str, year: int | None = None, engine: str = "") -> str:
    return "|".join(
        [
            normalize_catalog_text(make),
            normalize_catalog_text(model),
            str(year or ""),
            normalize_catalog_text(engine),
        ]
    )


def trusted_defect_source(url: str) -> tuple[str, str] | None:
    hostname = urllib.parse.urlparse(url).hostname or ""
    hostname = hostname.casefold().removeprefix("www.")
    for domain, source in DEFECT_RESEARCH_SOURCES.items():
        if hostname == domain or hostname.endswith(f".{domain}"):
            return source
    return None


def search_defect_source_candidates(
    make: str,
    model: str,
    year: int | None = None,
    engine: str = "",
) -> dict[str, Any]:
    if not defect_research_configured():
        raise RuntimeError("Ricerca fonti non configurata sul server.")
    clean_make = str(make or "").strip()
    clean_model = str(model or "").strip()
    if not clean_make or not clean_model:
        raise ValueError("Marca e modello sono obbligatori.")
    cache_key = defect_research_cache_key(clean_make, clean_model, year, engine)
    now = time.time()
    with DEFECT_RESEARCH_LOCK:
        cached = DEFECT_RESEARCH_CACHE.get(cache_key)
        if cached and now - cached[0] < DEFECT_RESEARCH_CACHE_TTL_SECONDS:
            return {**cached[1], "fromCache": True}

    context_terms = " ".join(
        term for term in [str(year or ""), str(engine or "").strip()] if term
    )
    query = (
        f'"{clean_make}" "{clean_model}" {context_terms} '
        "(richiamo OR recall OR campagna OR bollettino OR forum OR community "
        "OR proprietari OR difetto OR problema)"
    )
    params = urllib.parse.urlencode(
        {
            "q": query,
            "count": 20,
            "country": "it",
            "search_lang": "it",
            "safesearch": "moderate",
        }
    )
    request = urllib.request.Request(
        f"https://api.search.brave.com/res/v1/web/search?{params}",
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "AutoStoricoDefectResearch/1.0",
            "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("type") == "ErrorResponse":
        raise RuntimeError(str(data.get("message") or "Brave Search error"))

    candidates: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in data.get("web", {}).get("results", []) or []:
        url = str(item.get("url") or "").strip()
        trusted = trusted_defect_source(url)
        if not trusted or not url or url in seen_urls:
            continue
        source_name, source_type = trusted
        seen_urls.add(url)
        research_category = (
            "community"
            if source_type == "community_candidate"
            else "official_or_technical"
        )
        candidates.append(
            {
                "title": str(item.get("title") or "Fonte da verificare"),
                "url": url,
                "snippet": " ".join(
                    [
                        str(item.get("description") or ""),
                        *[str(value) for value in item.get("extra_snippets") or []],
                    ]
                ).strip(),
                "sourceName": source_name,
                "sourceType": source_type,
                "researchCategory": research_category,
                "status": "pending_review",
            }
        )
        if len(candidates) >= 10:
            break

    result = {
        "make": clean_make,
        "model": clean_model,
        "year": year,
        "engine": str(engine or "").strip(),
        "query": query,
        "researchCoverage": ["official_recalls", "manufacturer", "community"],
        "candidates": candidates,
        "count": len(candidates),
        "fromCache": False,
        "disclaimer": (
            "Candidati automatici: devono essere verificati e approvati prima "
            "di entrare nel catalogo visibile agli utenti."
        ),
    }
    with DEFECT_RESEARCH_LOCK:
        DEFECT_RESEARCH_CACHE[cache_key] = (now, result)
    return result


def market_cache_key(payload: dict[str, Any]) -> str:
    """Keep estimates reusable without retaining a vehicle plate in memory."""
    km = max(0, int(parse_float(payload.get("km"), 0)))
    fields = {
        "vehicleType": str(payload.get("vehicleType") or "").strip().lower(),
        "brand": str(payload.get("brand") or payload.get("make") or "").strip().lower(),
        "model": str(payload.get("model") or "").strip().lower(),
        "year": parse_year(payload.get("firstRegistrationDate")),
        "fuelType": str(payload.get("fuelType") or "").strip().lower(),
        "engineCc": parse_engine_cc(payload.get("engineDisplacement")),
        "gearbox": str(payload.get("gearbox") or "").strip().lower(),
        "trim": str(payload.get("trim") or "").strip().lower(),
        "condition": str(payload.get("condition") or "").strip().lower(),
        "kmBucket": (km // 5000) * 5000,
    }
    serialized = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def cached_market_estimate(cache_key: str) -> dict[str, Any] | None:
    now = time.time()
    with MARKET_GUARD_LOCK:
        cached = MARKET_CACHE.get(cache_key)
        if cached is None:
            return None
        created_at, estimate = cached
        if now - created_at > MARKET_CACHE_TTL_SECONDS:
            MARKET_CACHE.pop(cache_key, None)
            return None
        return estimate


def cache_market_estimate(cache_key: str, estimate: dict[str, Any]) -> None:
    with MARKET_GUARD_LOCK:
        MARKET_CACHE[cache_key] = (time.time(), estimate)


def can_run_market_search(client_id: str) -> bool:
    return can_run_limited_request(MARKET_REQUESTS, client_id, MARKET_RATE_LIMIT)


def can_run_premium_verification(client_id: str) -> bool:
    return can_run_limited_request(
        PREMIUM_VERIFY_REQUESTS, client_id, PREMIUM_VERIFY_RATE_LIMIT
    )


def can_run_limited_request(
    requests: dict[str, list[float]], client_id: str, limit: int
) -> bool:
    now = time.time()
    with MARKET_GUARD_LOCK:
        recent = [
            timestamp
            for timestamp in requests.get(client_id, [])
            if now - timestamp < MARKET_RATE_WINDOW_SECONDS
        ]
        if len(recent) >= limit:
            requests[client_id] = recent
            return False
        recent.append(now)
        requests[client_id] = recent
        return True


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace(".", "").replace(",", ".")
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_engine_cc(value: Any) -> int:
    text = str(value or "").lower().strip()
    if not text:
        return 0
    if "." in text and not re.search(r"\d{4}", text):
        as_liters = parse_float(text)
        if 0.6 <= as_liters <= 8.0:
            return int(round(as_liters * 1000))
    cc = int(parse_float(text))
    if 600 <= cc <= 8000:
        return cc
    compact = re.sub(r"\D", "", text)
    if compact.isdigit():
        cc = int(compact)
        if 600 <= cc <= 8000:
            return cc
    return 0


def engine_query_label(engine_cc: int) -> str:
    if engine_cc <= 0:
        return ""
    liters = engine_cc / 1000
    if liters < 1:
        return f"{engine_cc} cc"
    return f"{liters:.1f}".replace(".", ",")


def parse_year(first_registration_date: Any) -> int | None:
    text = str(first_registration_date or "").strip()
    if not text:
        return None
    year_text = text[:4]
    if year_text.isdigit():
        year = int(year_text)
        if 1950 <= year <= 2100:
            return year
    return None


def round_to_hundreds(value: float) -> int:
    return int(round(value / 100.0) * 100)


def median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def extract_price(text: str) -> int | None:
    normalized = text.replace("\u00a0", " ")
    patterns = [
        r"(?:€|EUR)\s*([0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]{4,6})",
        r"([0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]{4,6})\s*(?:€|EUR)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            price = int(re.sub(r"\D", "", match.group(1)))
            if 300 <= price <= 250000:
                return price
    return None


def build_market_queries(payload: dict[str, Any], year: int | None) -> list[str]:
    brand = str(payload.get("brand") or payload.get("make") or "").strip()
    model = str(payload.get("model") or "").strip()
    trim = str(payload.get("trim") or "").strip()
    fuel_type = str(payload.get("fuelType") or "").strip()
    engine_cc = parse_engine_cc(payload.get("engineDisplacement") or payload.get("engineCc"))
    engine_label = engine_query_label(engine_cc)
    km = int(parse_float(payload.get("km")))
    base_core = " ".join(
        part for part in [brand, model, trim, engine_label, fuel_type] if part
    )
    query_core = base_core
    if year:
        base_core = f"{base_core} {year}".strip()
        query_core = f"{query_core} {year}"
    if km > 0:
        rounded_km = int(round(km / 10000) * 10000)
        query_core = f"{query_core} {rounded_km} km"
    if not query_core.strip():
        return []
    broad_queries = [
        f"{query_core} auto usata prezzo",
        f"{base_core} usata prezzo vendita privati",
        f"{base_core} AutoScout24 Subito Automobile prezzo",
    ]
    if year:
        age = max(0, min(40, 2026 - year))
        historic_kind = historic_classification(age, brand, model, trim)
        if historic_kind in {"collectible_historic", "young_collectible"}:
            broad_queries.extend(
                [
                    f"{base_core} storica prezzo",
                    f"{base_core} epoca ASI prezzo",
                    f"{base_core} collezione valore",
                ]
            )
        elif historic_kind == "historic_age_common":
            broad_queries.append(f"{base_core} storica prezzo vendita privati")
    site_queries = [f"{base_core} prezzo site:{domain}" for _, domain in MARKET_SITES]
    return broad_queries + site_queries


def extract_listing_price(text: str) -> int | None:
    normalized = html.unescape(text).replace("\u00a0", " ")
    price_token = r"(?:\u20ac|EUR)"
    number_token = r"([0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]{4,6})"
    for pattern in (rf"{price_token}\s*{number_token}", rf"{number_token}\s*{price_token}"):
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            price = int(re.sub(r"\D", "", match.group(1)))
            if 300 <= price <= 250000:
                return price
    return None


def extract_listing_year(text: str) -> int | None:
    current_year = 2026
    for match in re.finditer(r"\b(19[5-9][0-9]|20[0-2][0-9])\b", text):
        year = int(match.group(1))
        if 1950 <= year <= current_year + 1:
            return year
    return None


def extract_listing_km(text: str) -> int | None:
    normalized = html.unescape(text).replace("\u00a0", " ")
    patterns = [
        r"(?<![A-Za-z0-9])([0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]{4,6})\s*(?:km|chilometri)\b",
        r"(?:km|chilometri)\s*(?<![A-Za-z0-9])([0-9]{1,3}(?:[.\s][0-9]{3})+|[0-9]{4,6})\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            km = int(re.sub(r"\D", "", match.group(1)))
            if 1000 <= km <= 500000:
                return km
    return None


def quartile(sorted_values: list[float], ratio: float) -> float:
    if not sorted_values:
        return 0
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] + ((sorted_values[upper] - sorted_values[lower]) * fraction)


def parse_price_amount(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,\.]", "", text)
    if not cleaned:
        return None
    try:
        if "," in cleaned:
            amount = float(cleaned.replace(".", "").replace(",", "."))
        elif cleaned.count(".") == 1 and len(cleaned.rsplit(".", 1)[1]) <= 2:
            amount = float(cleaned)
        else:
            amount = float(cleaned.replace(".", ""))
    except ValueError:
        return None
    price = int(round(amount))
    if 300 <= price <= 250000:
        return price
    return None


def market_source_name(link: str, fallback: str = "Fonte web") -> str:
    return next(
        (name for name, domain in MARKET_SITES if domain in link),
        fallback,
    )


def is_market_url(link: str) -> bool:
    return any(domain in link for _, domain in MARKET_SITES)


def source_weight(link: str) -> float:
    if any(domain in link for domain in DIRECT_MARKET_DOMAINS):
        return 1.0
    if any(domain in link for domain in REFERENCE_MARKET_DOMAINS):
        return 0.65
    return 0.45


def weighted_median(items: list[dict[str, Any]]) -> float:
    rows = sorted(
        (
            (float(item["price"]), float(item.get("weight") or 1.0))
            for item in items
            if item.get("price")
        ),
        key=lambda row: row[0],
    )
    if not rows:
        return 0
    total_weight = sum(weight for _, weight in rows)
    midpoint = total_weight / 2
    running = 0.0
    for price, weight in rows:
        running += weight
        if running >= midpoint:
            return price
    return rows[-1][0]


def vehicle_text(brand: str, model: str, trim: str = "") -> str:
    return f"{brand} {model} {trim}".lower()


def is_collectible_variant(brand: str, model: str, trim: str = "") -> bool:
    text = vehicle_text(brand, model, trim)
    collectible_terms = [
        "4x4",
        "sisley",
        "selecta",
        "trekking",
        "val d'isere",
        "val d isere",
        "young 4x4",
        "country club",
    ]
    return any(term in text for term in collectible_terms)


def is_basic_old_economy_car(brand: str, model: str, trim: str = "") -> bool:
    text = vehicle_text(brand, model, trim)
    if is_collectible_variant(brand, model, trim):
        return False
    basic_models = [
        "fiat panda",
        "fiat punto",
        "fiat seicento",
        "fiat cinquecento",
        "ford fiesta",
        "renault clio",
        "peugeot 106",
        "citroen saxo",
        "opel corsa",
    ]
    return any(name in text for name in basic_models)


def historic_classification(age: int, brand: str, model: str, trim: str = "") -> str:
    if age < 20:
        return "ordinary"
    if is_collectible_variant(brand, model, trim):
        return "collectible_historic" if age >= 30 else "young_collectible"
    if age >= 30:
        return "historic_age_common"
    return "potential_historic_interest"


def extract_price_from_listing_page(link: str) -> int | None:
    if not link or not is_market_url(link):
        return None
    request = urllib.request.Request(
        link,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "it-IT,it;q=0.9",
            "User-Agent": "Mozilla/5.0 AutoStoricoValueBot/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return None
        raw = response.read(900000).decode("utf-8", errors="ignore")
    page = html.unescape(raw)
    structured_patterns = [
        r'"price"\s*:\s*"?([0-9]{3,6}(?:[.,][0-9]{1,2})?)"?',
        r'"priceAmount"\s*:\s*"?([0-9]{3,6}(?:[.,][0-9]{1,2})?)"?',
        r'property=["\'](?:product:price:amount|og:price:amount)["\'][^>]*content=["\']([0-9]{3,6}(?:[.,][0-9]{1,2})?)',
        r'content=["\']([0-9]{3,6}(?:[.,][0-9]{1,2})?)["\'][^>]*property=["\'](?:product:price:amount|og:price:amount)["\']',
    ]
    for pattern in structured_patterns:
        for match in re.finditer(pattern, page, flags=re.IGNORECASE):
            price = parse_price_amount(match.group(1))
            if price is not None:
                return price
    return extract_listing_price(page[:300000])


def is_relevant_listing_text(text: str, payload: dict[str, Any]) -> bool:
    cleaned = text.lower()
    brand = str(payload.get("brand") or payload.get("make") or "").strip().lower()
    model = str(payload.get("model") or "").strip().lower()
    target_year = parse_year(payload.get("firstRegistrationDate") or payload.get("year"))
    target_km = int(parse_float(payload.get("km")))
    if brand and brand not in cleaned:
        return False
    if model:
        model_tokens = [token for token in re.split(r"\s+", model) if len(token) > 1]
        if model_tokens and not all(token in cleaned for token in model_tokens):
            return False
    listing_year = extract_listing_year(text)
    if target_year and listing_year and abs(listing_year - target_year) > 1:
        return False
    listing_km = extract_listing_km(text)
    if target_km > 0 and listing_km:
        km_tolerance = max(30000, int(target_km * 0.40))
        if abs(listing_km - target_km) > km_tolerance:
            return False
    return True


def listing_from_search_item(item: dict[str, Any], fallback_source: str = "Fonte web", payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or item.get("description") or "")
    link = str(item.get("link") or item.get("url") or item.get("product_link") or "")
    item_text = json.dumps(item, ensure_ascii=False)
    combined_text = f"{title} {snippet} {link} {item_text}"
    if not link:
        return None
    if not is_market_url(link):
        return None
    if payload is not None and not is_relevant_listing_text(combined_text, payload):
        return None
    extracted_price = item.get("extracted_price")
    price = (
        int(float(extracted_price))
        if extracted_price is not None
        else extract_listing_price(f"{title} {snippet} {item_text}")
    )
    if price is None:
        try:
            price = extract_price_from_listing_page(link)
        except Exception:
            price = None
    if price is None or not 300 <= price <= 250000:
        return None
    return {
        "source": market_source_name(link, str(item.get("source") or fallback_source)),
        "title": title[:140],
        "url": link,
        "price": price,
        "year": extract_listing_year(combined_text),
        "km": extract_listing_km(combined_text),
        "weight": source_weight(link),
    }


def google_market_search(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not GOOGLE_CSE_ENABLED or not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
        return []
    params = urllib.parse.urlencode(
        {
            "key": GOOGLE_CSE_API_KEY,
            "cx": GOOGLE_CSE_ID,
            "q": query,
            "num": 5,
            "gl": "it",
            "lr": "lang_it",
        }
    )
    url = f"https://www.googleapis.com/customsearch/v1?{params}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "AutoStoricoValueBot/1.0"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
    results = []
    for item in data.get("items", []):
        listing = listing_from_search_item(item, payload=payload)
        if listing is not None:
            results.append(listing)
    return results


def brave_market_search(query: str, payload: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not BRAVE_SEARCH_API_KEY:
        return []
    params = urllib.parse.urlencode(
        {
            "q": query,
            "count": 8,
            "country": "it",
            "search_lang": "it",
            "safesearch": "moderate",
        }
    )
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "AutoStoricoValueBot/1.0",
            "X-Subscription-Token": BRAVE_SEARCH_API_KEY,
        },
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
    results = []
    search_items = list(data.get("web", {}).get("results", []) or [])
    for item in search_items:
        item["snippet"] = " ".join(
            [
                str(item.get("description") or ""),
                " ".join(str(value) for value in item.get("extra_snippets") or []),
            ]
        )
        listing = listing_from_search_item(item, payload=payload)
        if listing is not None:
            results.append(listing)
    if diagnostics is not None:
        diagnostics["providers"].append(
            {
                "provider": "brave",
                "query": query,
                "items": len(search_items),
                "priced": len(results),
                "sampleUrls": [str(item.get("url") or "") for item in search_items[:3]],
            }
        )
    return results


def serpapi_market_search(query: str, payload: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not SERPAPI_API_KEY:
        return []
    params = urllib.parse.urlencode(
        {
            "engine": "google",
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "google_domain": "google.it",
            "gl": "it",
            "hl": "it",
            "num": 10,
        }
    )
    url = f"https://serpapi.com/search.json?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "AutoStoricoValueBot/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(str(data.get("error")))
    results = []
    search_items = []
    for section_name in [
        "organic_results",
        "ads",
        "inline_shopping_results",
        "shopping_results",
        "top_shopping_results",
    ]:
        search_items.extend(data.get(section_name) or [])
    for item in search_items:
        listing = listing_from_search_item(item, payload=payload)
        if listing is not None:
            results.append(listing)
    if diagnostics is not None:
        diagnostics["providers"].append(
            {
                "provider": "serpapi_google",
                "query": query,
                "items": len(search_items),
                "priced": len(results),
                "sampleUrls": [
                    str(item.get("link") or item.get("product_link") or "")
                    for item in search_items[:3]
                ],
            }
        )
    return results


def serpapi_shopping_market_search(query: str, payload: dict[str, Any], diagnostics: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not SERPAPI_API_KEY:
        return []
    params = urllib.parse.urlencode(
        {
            "engine": "google_shopping",
            "q": query.replace(" site:", " "),
            "api_key": SERPAPI_API_KEY,
            "google_domain": "google.it",
            "gl": "it",
            "hl": "it",
            "location": "Italy",
        }
    )
    url = f"https://serpapi.com/search.json?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "AutoStoricoValueBot/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode("utf-8"))
    if data.get("error"):
        raise RuntimeError(str(data.get("error")))
    results = []
    shopping_groups = list(data.get("shopping_results") or [])
    for category in data.get("categorized_shopping_results") or []:
        shopping_groups.extend(category.get("shopping_results") or [])
    for item in shopping_groups:
        listing = listing_from_search_item(item, fallback_source="Google Shopping", payload=payload)
        if listing is not None:
            results.append(listing)
    if diagnostics is not None:
        diagnostics["providers"].append(
            {
                "provider": "serpapi_shopping",
                "query": query,
                "items": len(shopping_groups),
                "priced": len(results),
                "sampleUrls": [
                    str(item.get("link") or item.get("product_link") or "")
                    for item in shopping_groups[:3]
                ],
            }
        )
    return results


def fetch_market_sources(payload: dict[str, Any], year: int | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    configured_providers = {
        "brave": bool(BRAVE_SEARCH_API_KEY),
        "serpapi": bool(SERPAPI_API_KEY),
        "google_cse": bool(GOOGLE_CSE_ENABLED and GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID),
    }
    diagnostics: dict[str, Any] = {
        "configuredProviders": configured_providers,
        "providers": [],
        "errors": [],
    }
    if not MARKET_SEARCH_ENABLED:
        return [], diagnostics
    listings: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in build_market_queries(payload, year):
        query_results: list[dict[str, Any]] = []
        providers = [
            ("brave", configured_providers["brave"], lambda: brave_market_search(query, payload, diagnostics)),
            ("serpapi_google", configured_providers["serpapi"], lambda: serpapi_market_search(query, payload, diagnostics)),
            ("serpapi_shopping", configured_providers["serpapi"], lambda: serpapi_shopping_market_search(query, payload, diagnostics)),
            ("google_cse", configured_providers["google_cse"], lambda: google_market_search(query, payload)),
        ]
        for provider_name, is_configured, provider in providers:
            if not is_configured:
                continue
            try:
                provider_results = provider()
            except Exception as exc:
                diagnostics["errors"].append(
                    {
                        "provider": provider_name,
                        "query": query,
                        "error": str(exc)[:180],
                    }
                )
                continue
            if provider_results:
                query_results.extend(provider_results)
            # Brave is the primary source. If it returns too few priced listings,
            # use the next configured provider as a fallback rather than turning a
            # thin web result into an internal-only estimate.
            if len(query_results) >= MINIMUM_MARKET_LISTINGS:
                break
        for listing in query_results:
            url = str(listing.get("url") or "")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            listings.append(listing)
        if len(listings) >= 12:
            break
    diagnostics["pricesFound"] = len(listings)
    return listings[:20], diagnostics


def market_estimate_from_sources(
    listings: list[dict[str, Any]],
    internal_average: float,
) -> tuple[float | None, list[dict[str, Any]]]:
    if not listings:
        return None, []
    prices = [float(item["price"]) for item in listings if item.get("price")]
    if not prices:
        return None, []
    center = weighted_median(listings)
    lower_limit = max(300.0, center * 0.70)
    upper_limit = center * 1.35
    if internal_average > 0:
        lower_limit = max(lower_limit, internal_average * 0.62)
        upper_limit = min(upper_limit, internal_average * 1.22)
    filtered = [
        item
        for item in listings
        if lower_limit <= float(item.get("price") or 0) <= upper_limit
    ]
    filtered_prices = [float(item["price"]) for item in filtered]
    if len(filtered_prices) < 3 and internal_average > 0:
        relaxed_lower = max(300.0, internal_average * 0.55)
        relaxed_upper = internal_average * 1.30
        filtered = [
            item
            for item in listings
            if relaxed_lower <= float(item.get("price") or 0) <= relaxed_upper
        ]
        filtered_prices = [float(item["price"]) for item in filtered]
    if len(filtered_prices) < 3:
        return None, filtered
    ordered_prices = sorted(filtered_prices)
    q1 = quartile(ordered_prices, 0.25)
    q3 = quartile(ordered_prices, 0.75)
    iqr = q3 - q1
    if iqr > 0:
        iqr_lower = max(300.0, q1 - (1.5 * iqr))
        iqr_upper = q3 + (1.5 * iqr)
        iqr_filtered = [
            item
            for item in filtered
            if iqr_lower <= float(item.get("price") or 0) <= iqr_upper
        ]
        if len(iqr_filtered) >= 3:
            filtered = iqr_filtered
    source_average = weighted_median(filtered)
    if internal_average > 0:
        divergence = abs(source_average - internal_average) / max(internal_average, 1)
        if divergence > 0.18:
            blended = (source_average * 0.55) + (internal_average * 0.45)
        else:
            blended = (source_average * 0.75) + (internal_average * 0.25)
    else:
        blended = source_average
    return blended, filtered


def asking_to_private_sale_factor(
    age: int,
    km: float,
    is_moto: bool,
    brand: str = "",
    model: str = "",
    trim: str = "",
) -> float:
    if is_moto:
        return 0.90 if age <= 5 else 0.86
    historic_kind = historic_classification(age, brand, model, trim)
    if historic_kind == "collectible_historic":
        return 0.82
    if historic_kind == "young_collectible":
        return 0.88
    if age >= 25 and is_basic_old_economy_car(brand, model, trim):
        if km >= 180000:
            return 0.45
        if km >= 120000:
            return 0.52
        return 0.60
    if historic_kind == "historic_age_common":
        if km >= 180000:
            return 0.62
        if km >= 120000:
            return 0.68
        return 0.74
    if historic_kind == "potential_historic_interest":
        if km >= 180000:
            return 0.78
        if km >= 120000:
            return 0.82
        return 0.86
    if age >= 12 or km >= 140000:
        return 0.86
    if age >= 8 or km >= 100000:
        return 0.89
    if age >= 4:
        return 0.92
    return 0.95


def private_sale_age_factor(age: int, is_moto: bool) -> float:
    if is_moto:
        anchors = {
            0: 0.88,
            1: 0.78,
            2: 0.68,
            3: 0.60,
            5: 0.48,
            8: 0.36,
            10: 0.30,
            15: 0.20,
            20: 0.12,
            30: 0.07,
        }
    else:
        anchors = {
            0: 0.92,
            1: 0.82,
            2: 0.72,
            3: 0.64,
            5: 0.50,
            8: 0.36,
            10: 0.29,
            12: 0.235,
            15: 0.18,
            20: 0.10,
            30: 0.04,
        }
    age = max(0, min(30, age))
    points = sorted(anchors)
    if age in anchors:
        return anchors[age]
    lower = max(point for point in points if point < age)
    upper = min(point for point in points if point > age)
    ratio = (age - lower) / (upper - lower)
    return anchors[lower] + ((anchors[upper] - anchors[lower]) * ratio)


def normalize_condition(value: str) -> str:
    cleaned = value.strip().lower()
    if cleaned.startswith("ottim"):
        return "Ottimo"
    if cleaned.startswith("suff"):
        return "Sufficiente"
    return "Buono"


def estimated_new_value(vehicle_type: str, brand: str, model: str, trim: str = "", engine_cc: int = 0, fuel_type: str = "") -> float:
    if vehicle_type.lower() == "moto":
        return 7500

    brand_model = f"{brand} {model} {trim}".lower()
    premium = ["audi", "bmw", "mercedes", "lexus", "tesla", "volvo"]
    upper = ["alfa romeo", "mini", "jeep", "cupra", "land rover", "jaguar"]
    economy = ["fiat", "dacia", "citroen", "renault", "peugeot", "opel", "ford", "hyundai", "kia"]

    if "panda" in brand_model:
        base = 14500
    elif any(name in brand_model for name in ["punto", "seicento", "cinquecento"]):
        base = 13500
    elif any(name in brand_model for name in premium):
        base = 32000
    elif any(name in brand_model for name in upper):
        base = 26000
    elif any(name in brand_model for name in economy):
        base = 17500
    else:
        base = 22000
    fuel = fuel_type.lower()
    if "elettr" in fuel:
        base *= 1.25
    elif "ibrid" in fuel or "hybrid" in fuel:
        base *= 1.12
    elif "diesel" in fuel and engine_cc >= 1500:
        base *= 1.05
    if engine_cc:
        if engine_cc <= 1000:
            base *= 0.92
        elif engine_cc <= 1400:
            base *= 1.00
        elif engine_cc <= 2000:
            base *= 1.08
        else:
            base *= 1.12
    return base


def normalize_previous_owners(value: str) -> str:
    cleaned = value.strip().lower()
    if 'piu' in cleaned or 'oltre' in cleaned or '2+' in cleaned:
        return 'Piu di 2 proprietari'
    if cleaned.startswith('2'):
        return '2 proprietari'
    return '1 proprietario'


def vehicle_detail_factor(fuel_type: str, gearbox: str, trim: str, condition: str, tires_changed: bool = False, tire_type: str = '', air_conditioning_ok: bool = False, previous_owners: str = '1 proprietario', engine_cc: int = 0) -> float:
    factor = 1.0
    normalized_condition = normalize_condition(condition).lower()
    if normalized_condition.startswith("ottim"):
        factor += 0.10
    elif normalized_condition.startswith("buon"):
        factor += 0.02
    elif normalized_condition.startswith("suff"):
        factor -= 0.18

    if "auto" in gearbox.lower():
        factor += 0.03

    fuel = fuel_type.lower()
    if "elettr" in fuel:
        factor += 0.05
    elif "hybrid" in fuel or "ibrid" in fuel:
        factor += 0.04
    elif "gpl" in fuel or "metano" in fuel:
        factor += 0.02
    elif "diesel" in fuel:
        factor -= 0.01

    if engine_cc:
        if engine_cc <= 1000:
            factor -= 0.03
        elif engine_cc <= 1400:
            factor += 0.01
        elif engine_cc <= 2000:
            factor += 0.03
        else:
            factor += 0.01

    if trim.strip():
        factor += 0.02
    if tires_changed:
        factor += 0.03
    if tire_type.strip():
        factor += 0.01
    if air_conditioning_ok:
        factor += 0.02
    owners = normalize_previous_owners(previous_owners)
    if owners == '1 proprietario':
        factor += 0.03
    elif owners == 'Piu di 2 proprietari':
        factor -= 0.04
    return max(0.80, min(1.20, factor))


def market_floor_value(
    vehicle_type: str,
    brand: str,
    model: str,
    trim: str,
    condition: str,
    age: int,
) -> float:
    brand_model = f"{brand} {model} {trim}".lower()
    normalized_condition = normalize_condition(condition)
    is_moto = vehicle_type.lower() == "moto"
    is_economy = any(
        name in brand_model
        for name in ["fiat", "dacia", "citroen", "renault", "peugeot", "opel", "ford", "hyundai", "kia"]
    )
    is_premium_or_rare = any(
        name in brand_model
        for name in ["audi", "bmw", "mercedes", "porsche", "ferrari", "land rover", "jaguar", "alfa romeo"]
    )
    if is_moto:
        if age >= 25:
            return 350 if normalized_condition == "Sufficiente" else 550
        return 500 if normalized_condition == "Sufficiente" else 700

    if age >= 25:
        if is_economy:
            if normalized_condition == "Ottimo":
                return 1800
            if normalized_condition == "Buono":
                return 1100
            return 600
        if is_premium_or_rare:
            if normalized_condition == "Ottimo":
                return 2600
            if normalized_condition == "Buono":
                return 1600
            return 900
        return 600 if normalized_condition == "Sufficiente" else 1000

    if age >= 15:
        if normalized_condition == "Ottimo":
            return 4200 if is_premium_or_rare else 1800
        if normalized_condition == "Buono":
            return 3000 if is_premium_or_rare else 1200
        return 1800 if is_premium_or_rare else 700

    return 700 if normalized_condition == "Sufficiente" else 1000


def estimate_vehicle_value(payload: dict[str, Any]) -> dict[str, Any]:
    vehicle_type = str(payload.get("vehicleType") or "Auto").strip()
    brand = str(payload.get("brand") or payload.get("make") or "").strip()
    model = str(payload.get("model") or "").strip()
    km = parse_float(payload.get("km"))
    fuel_type = str(payload.get("fuelType") or "").strip()
    engine_cc = parse_engine_cc(payload.get("engineDisplacement") or payload.get("engineCc"))
    gearbox = str(payload.get("gearbox") or "").strip()
    trim = str(payload.get("trim") or "").strip()
    condition = str(payload.get("condition") or "Buono").strip()
    tires_changed = bool(payload.get("tiresChanged") is True)
    tire_type = str(payload.get("tireType") or "").strip()
    air_conditioning_ok = bool(payload.get("airConditioningOk") is True)
    previous_owners = str(payload.get("previousOwners") or "1 proprietario").strip()
    year = parse_year(payload.get("firstRegistrationDate") or payload.get("year"))

    current_year = 2026
    age = 6 if year is None else max(0, min(30, current_year - year))
    actual_age = 6 if year is None else max(0, current_year - year)
    historic_kind = historic_classification(actual_age, brand, model, trim)
    base_value = estimated_new_value(vehicle_type, brand, model, trim, engine_cc, fuel_type)
    is_moto = vehicle_type.lower() == "moto"

    age_factor = private_sale_age_factor(age, is_moto)
    expected_km = max(1, age) * (6000 if is_moto else 13000)
    mileage_ratio = km / expected_km if expected_km else 1
    mileage_factor = max(0.62, min(1.18, 1.10 - ((mileage_ratio - 1) * 0.18)))

    history_factor = 1.0
    if int(payload.get("revisionHistoryCount") or 0) > 0:
        history_factor += 0.04
    if int(payload.get("insuranceHistoryCount") or 0) > 0:
        history_factor += 0.02
    if int(payload.get("taxHistoryCount") or 0) > 0:
        history_factor += 0.02
    if parse_float(payload.get("worksTotal")) > 0:
        history_factor += 0.03
    if int(payload.get("documentsCount") or 0) > 0:
        history_factor += 0.02

    detail_factor = vehicle_detail_factor(fuel_type, gearbox, trim, condition, tires_changed, tire_type, air_conditioning_ok, previous_owners, engine_cc)
    raw_value = base_value * age_factor * mileage_factor * history_factor * detail_factor
    floor_value = market_floor_value(vehicle_type, brand, model, trim, condition, age)
    internal_average = max(floor_value, raw_value)
    listings, market_diagnostics = fetch_market_sources(payload, year)
    market_average, filtered_listings = market_estimate_from_sources(
        listings,
        internal_average,
    )
    if market_average is not None:
        market_average *= asking_to_private_sale_factor(
            age,
            km,
            is_moto,
            brand,
            model,
            trim,
        )
    average = market_average if market_average is not None else internal_average
    spread = 0.26 if year is None else 0.28 if age >= 20 else 0.16
    min_value = max(floor_value * 0.75, average * (1 - spread))
    max_value = max(min_value + 200, average * (1 + spread))

    has_details = bool(fuel_type and engine_cc and gearbox and condition and previous_owners)
    matched_count = len(filtered_listings)
    market_based = matched_count >= MINIMUM_MARKET_LISTINGS
    market_configured = any(market_diagnostics.get("configuredProviders", {}).values())
    source_names = sorted({str(item.get("source") or "Fonte web") for item in filtered_listings})
    confidence = (
        f"Alta: valore confrontato con {matched_count} annunci/fonti web compatibili."
        if matched_count >= 8
        else f"Media: valore confrontato con {matched_count} annunci/fonti web compatibili."
        if market_based
        else "Server online, ma fonti mercato non configurate. Aggiungi SerpApi o Brave su Render per usare prezzi web reali."
        if not market_configured
        else "Server online: fonti mercato interrogate, ma non ci sono abbastanza prezzi confrontabili. Stima interna usata solo come fallback."
        if year is not None and km > 0 and has_details
        else "Media: compila anno, km, stato, cilindrata, gomme, aria condizionata, proprietari, cambio, alimentazione e lavori."
    )
    method = (
        "Valore calcolato partendo da annunci/fonti mercato compatibili, poi corretto verso un prezzo realistico di vendita tra privati."
        if market_based
        else "API online ma fonti mercato assenti: configura SERPAPI_API_KEY o BRAVE_SEARCH_API_KEY su Render."
        if not market_configured
        else "Server online ma confronto mercato insufficiente: AutoStorico non considera questo valore come prezzo web definitivo."
    )

    response = {
        "minValue": round_to_hundreds(min_value),
        "averageValue": round_to_hundreds(average),
        "maxValue": round_to_hundreds(max_value),
        "confidence": confidence,
        "method": method,
        "marketType": "vendita_privata",
        "historicCriteria": historic_kind,
        "vehicleAge": actual_age,
        "matchedListings": matched_count,
        "minimumListingsRequired": MINIMUM_MARKET_LISTINGS,
        "sourcesUsed": source_names,
        "marketBased": market_based,
        "marketCheckedAt": datetime.now(timezone.utc).isoformat(),
        "serverOnline": True,
        "marketSearchConfigured": market_configured,
        "configuredProviders": market_diagnostics.get("configuredProviders", {}),
        "sampleListings": filtered_listings[:5],
    }
    if payload.get("debug") is True:
        response["marketDiagnostics"] = market_diagnostics
    return response


def google_play_service_account_json() -> str:
    """Load the credential from an environment value or Render secret file."""
    if GOOGLE_PLAY_SERVICE_ACCOUNT_JSON:
        return GOOGLE_PLAY_SERVICE_ACCOUNT_JSON
    if not GOOGLE_PLAY_SERVICE_ACCOUNT_FILE:
        return ""
    try:
        return Path(GOOGLE_PLAY_SERVICE_ACCOUNT_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def google_play_publisher_configured() -> bool:
    return bool(
        google_play_service_account_json()
        and GOOGLE_PLAY_PACKAGE_NAME
        and AuthorizedSession is not None
        and service_account is not None
    )


def premium_verification_configured() -> bool:
    return bool(google_play_publisher_configured() and GOOGLE_PLAY_SUBSCRIPTION_ID)


def product_verification_configured() -> bool:
    return bool(google_play_publisher_configured() and GOOGLE_PLAY_DEFECTS_GOLD_PRODUCT_ID)


def play_integrity_configured() -> bool:
    return google_play_publisher_configured()


def expected_purchase_nonce(
    purchase_token: str, product_id: str, integrity_salt: str
) -> str:
    protected_request = f"{product_id}\n{purchase_token}\n{integrity_salt}".encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(protected_request).digest()).decode(
        "ascii"
    ).rstrip("=")


def verify_play_integrity(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify that a premium request comes from the Play-recognized app."""
    integrity_token = str(payload.get("integrityToken") or "").strip()
    claimed_nonce = str(payload.get("integrityNonce") or "").strip()
    integrity_salt = str(payload.get("integritySalt") or "").strip()
    purchase_token = str(payload.get("purchaseToken") or "").strip()
    product_id = str(payload.get("productId") or "").strip()

    # Staged rollout: keep installed version 30 working until the new release
    # has reached users, then set AUTOSTORICO_PLAY_INTEGRITY_REQUIRED=1.
    if not integrity_token:
        if PLAY_INTEGRITY_REQUIRED:
            return {
                "ok": False,
                "message": "Aggiorna AutoStorico dalla pagina ufficiale Google Play.",
            }
        return {"ok": True, "legacy": True}

    if not play_integrity_configured():
        return {
            "ok": False,
            "message": "Controllo sicurezza Google Play temporaneamente non disponibile.",
        }
    if (
        len(integrity_token) < 80
        or len(claimed_nonce) < 32
        or len(integrity_salt) < 16
    ):
        return {"ok": False, "message": "Controllo integrita non valido."}

    expected_nonce = expected_purchase_nonce(
        purchase_token, product_id, integrity_salt
    )
    if not hmac.compare_digest(expected_nonce, claimed_nonce):
        return {"ok": False, "message": "Richiesta Premium alterata."}

    try:
        service_account_info = json.loads(google_play_service_account_json())
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/playintegrity"],
        )
        session = AuthorizedSession(credentials)
        package_name = urllib.parse.quote(GOOGLE_PLAY_PACKAGE_NAME, safe="")
        endpoint = (
            "https://playintegrity.googleapis.com/v1/"
            f"{package_name}:decodeIntegrityToken"
        )
        response = session.post(
            endpoint,
            json={"integrity_token": integrity_token},
            timeout=12,
        )
        if response.status_code != 200:
            return {
                "ok": False,
                "message": "Google Play non ha confermato l'integrita dell'app.",
            }

        verdict = response.json().get("tokenPayloadExternal") or {}
        request_details = verdict.get("requestDetails") or {}
        app_integrity = verdict.get("appIntegrity") or {}
        device_integrity = verdict.get("deviceIntegrity") or {}
        account_details = verdict.get("accountDetails") or {}

        if request_details.get("requestPackageName") != GOOGLE_PLAY_PACKAGE_NAME:
            return {"ok": False, "message": "Pacchetto app non riconosciuto."}
        if not hmac.compare_digest(
            str(request_details.get("nonce") or ""), expected_nonce
        ):
            return {"ok": False, "message": "Richiesta Premium alterata."}

        timestamp_ms = int(request_details.get("timestampMillis") or 0)
        age_seconds = abs((time.time() * 1000 - timestamp_ms) / 1000)
        if timestamp_ms <= 0 or age_seconds > PLAY_INTEGRITY_MAX_TOKEN_AGE_SECONDS:
            return {"ok": False, "message": "Controllo sicurezza scaduto. Riprova."}

        if app_integrity.get("appRecognitionVerdict") != "PLAY_RECOGNIZED":
            return {
                "ok": False,
                "message": "Installa la versione originale da Google Play.",
            }
        if app_integrity.get("packageName") != GOOGLE_PLAY_PACKAGE_NAME:
            return {"ok": False, "message": "Firma o pacchetto app non validi."}
        version_code = int(app_integrity.get("versionCode") or 0)
        if version_code < PLAY_INTEGRITY_MIN_VERSION_CODE:
            return {"ok": False, "message": "Aggiorna AutoStorico da Google Play."}

        device_verdicts = set(device_integrity.get("deviceRecognitionVerdict") or [])
        if "MEETS_DEVICE_INTEGRITY" not in device_verdicts:
            return {
                "ok": False,
                "message": "Il dispositivo non supera il controllo di sicurezza Google Play.",
            }
        if account_details.get("appLicensingVerdict") != "LICENSED":
            return {
                "ok": False,
                "message": "L'installazione non risulta autorizzata da Google Play.",
            }

        token_fingerprint = hashlib.sha256(integrity_token.encode("utf-8")).hexdigest()
        now = time.time()
        with PLAY_INTEGRITY_LOCK:
            expired_before = now - PLAY_INTEGRITY_MAX_TOKEN_AGE_SECONDS
            expired = [
                key for key, seen_at in PLAY_INTEGRITY_SEEN.items()
                if seen_at < expired_before
            ]
            for key in expired:
                PLAY_INTEGRITY_SEEN.pop(key, None)
            if token_fingerprint in PLAY_INTEGRITY_SEEN:
                return {"ok": False, "message": "Controllo sicurezza gia utilizzato."}
            PLAY_INTEGRITY_SEEN[token_fingerprint] = now
        return {"ok": True, "legacy": False}
    except (ValueError, KeyError, TypeError):
        return {"ok": False, "message": "Risposta sicurezza Google Play non valida."}
    except Exception:
        return {
            "ok": False,
            "message": "Controllo sicurezza Google Play temporaneamente non disponibile.",
        }


def verify_google_play_subscription(
    purchase_token: str, product_id: str
) -> dict[str, Any]:
    """Confirm a Google Play subscription server-side, never trusting the app."""
    if not premium_verification_configured():
        return {
            "active": False,
            "isTrial": False,
            "message": "Verifica Premium non ancora configurata.",
        }
    if product_id not in {
        GOOGLE_PLAY_SUBSCRIPTION_ID,
        GOOGLE_PLAY_DEFECTS_GOLD_PRODUCT_ID,
    }:
        return {
            "active": False,
            "isTrial": False,
            "message": "Piano AutoStorico non valido.",
        }
    if not purchase_token or len(purchase_token) < 12:
        return {
            "active": False,
            "isTrial": False,
            "message": "Token di acquisto non valido.",
        }

    try:
        service_account_info = json.loads(google_play_service_account_json())
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )
        session = AuthorizedSession(credentials)
        encoded_token = urllib.parse.quote(purchase_token, safe="")
        endpoint = (
            "https://androidpublisher.googleapis.com/androidpublisher/v3/"
            f"applications/{urllib.parse.quote(GOOGLE_PLAY_PACKAGE_NAME, safe='')}/"
            f"purchases/subscriptionsv2/tokens/{encoded_token}"
        )
        response = session.get(endpoint, timeout=12)
        if response.status_code != 200:
            return {
                "active": False,
                "isTrial": False,
                "message": "Acquisto non confermato da Google Play.",
            }
        data = response.json()
        line_items = list(data.get("lineItems") or [])
        matching_item = next(
            (item for item in line_items if item.get("productId") == product_id),
            None,
        )
        if matching_item is None:
            return {
                "active": False,
                "isTrial": False,
                "message": "Il piano acquistato non corrisponde ad AutoStorico Premium.",
            }
        state = str(data.get("subscriptionState") or "")
        expiry = str(matching_item.get("expiryTime") or "")
        inactive_states = {
            "SUBSCRIPTION_STATE_PENDING",
            "SUBSCRIPTION_STATE_ON_HOLD",
            "SUBSCRIPTION_STATE_PAUSED",
            "SUBSCRIPTION_STATE_EXPIRED",
        }
        active = state not in inactive_states and bool(expiry)
        return {
            "active": active,
            "isTrial": False,
            "expiresAt": expiry if active else None,
            "message": (
                "Premium verificato e attivo."
                if product_id == GOOGLE_PLAY_SUBSCRIPTION_ID
                else "Gold Difetti verificato e attivo."
            )
            if active
            else "Abbonamento non attivo.",
        }
    except (ValueError, KeyError, TypeError):
        return {
            "active": False,
            "isTrial": False,
            "message": "Configurazione Premium non valida sul server.",
        }
    except Exception:
        return {
            "active": False,
            "isTrial": False,
            "message": "Verifica Premium temporaneamente non disponibile.",
        }


def verify_google_play_product(
    purchase_token: str, product_id: str
) -> dict[str, Any]:
    """Confirm a Google Play one-time product server-side."""
    if not product_verification_configured():
        return {
            "active": False,
            "isTrial": False,
            "message": "Verifica acquisto Gold non ancora configurata.",
        }
    if product_id != GOOGLE_PLAY_DEFECTS_GOLD_PRODUCT_ID:
        return {
            "active": False,
            "isTrial": False,
            "message": "Prodotto Gold non valido.",
        }
    if not purchase_token or len(purchase_token) < 12:
        return {
            "active": False,
            "isTrial": False,
            "message": "Token di acquisto non valido.",
        }

    try:
        service_account_info = json.loads(google_play_service_account_json())
        credentials = service_account.Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/androidpublisher"],
        )
        session = AuthorizedSession(credentials)
        package_name = urllib.parse.quote(GOOGLE_PLAY_PACKAGE_NAME, safe="")
        encoded_product = urllib.parse.quote(product_id, safe="")
        encoded_token = urllib.parse.quote(purchase_token, safe="")
        endpoint = (
            "https://androidpublisher.googleapis.com/androidpublisher/v3/"
            f"applications/{package_name}/purchases/products/{encoded_product}"
            f"/tokens/{encoded_token}"
        )
        response = session.get(endpoint, timeout=12)
        if response.status_code != 200:
            return {
                "active": False,
                "isTrial": False,
                "message": "Acquisto Gold non confermato da Google Play.",
            }
        data = response.json()
        purchase_state = int(data.get("purchaseState", 1))
        active = purchase_state == 0
        return {
            "active": active,
            "isTrial": False,
            "message": "Difetti Gold acquistata." if active else "Acquisto Gold non attivo.",
        }
    except (ValueError, KeyError, TypeError):
        return {
            "active": False,
            "isTrial": False,
            "message": "Configurazione Gold non valida sul server.",
        }
    except Exception:
        return {
            "active": False,
            "isTrial": False,
            "message": "Verifica Gold temporaneamente non disponibile.",
        }


def cached_defect_entitlement(
    premium_token: str, gold_token: str
) -> dict[str, Any] | None:
    cache_key = hashlib.sha256(
        f"{premium_token}\n{gold_token}".encode("utf-8")
    ).hexdigest()
    now = time.time()
    with MARKET_GUARD_LOCK:
        cached = DEFECT_ENTITLEMENT_CACHE.get(cache_key)
        if not cached:
            return None
        created_at, entitlement = cached
        if now - created_at > DEFECT_ENTITLEMENT_CACHE_TTL_SECONDS:
            DEFECT_ENTITLEMENT_CACHE.pop(cache_key, None)
            return None
        return entitlement


def cache_defect_entitlement(
    premium_token: str, gold_token: str, entitlement: dict[str, Any]
) -> None:
    cache_key = hashlib.sha256(
        f"{premium_token}\n{gold_token}".encode("utf-8")
    ).hexdigest()
    with MARKET_GUARD_LOCK:
        DEFECT_ENTITLEMENT_CACHE[cache_key] = (time.time(), entitlement)


def verify_defect_online_entitlement(payload: dict[str, Any]) -> dict[str, Any]:
    if developer_device_is_authorized(payload.get("developerDeviceIdHash")):
        return {
            "ok": True,
            "status": 200,
            "message": "Autorizzazione verificata.",
        }
    premium_token = str(payload.get("premiumPurchaseToken") or "").strip()
    gold_token = str(payload.get("defectsGoldPurchaseToken") or "").strip()
    if not premium_token or not gold_token:
        return {
            "ok": False,
            "status": 402,
            "message": "Per Difetti Gold servono Premium attivo e acquisto Gold verificato.",
        }

    cached = cached_defect_entitlement(premium_token, gold_token)
    if cached is not None:
        return cached

    premium = verify_google_play_subscription(
        premium_token, GOOGLE_PLAY_SUBSCRIPTION_ID
    )
    if not premium.get("active"):
        return {
            "ok": False,
            "status": 402,
            "message": premium.get("message") or "Premium non attivo.",
        }
    gold = verify_google_play_subscription(
        gold_token, GOOGLE_PLAY_DEFECTS_GOLD_PRODUCT_ID
    )
    if not gold.get("active"):
        return {
            "ok": False,
            "status": 402,
            "message": gold.get("message") or "Difetti Gold non acquistata.",
        }

    entitlement = {"ok": True, "status": 200, "message": "Difetti Gold verificata."}
    cache_defect_entitlement(premium_token, gold_token, entitlement)
    return entitlement


def developer_device_is_authorized(device_id_hash: Any) -> bool:
    """Match the owner device only against a Render secret, never APK data."""
    candidate = str(device_id_hash or "").strip().lower()
    return bool(
        re.fullmatch(r"[a-f0-9]{64}", candidate)
        and re.fullmatch(r"[a-f0-9]{64}", DEVELOPER_DEVICE_ID_HASH)
        and hmac.compare_digest(candidate, DEVELOPER_DEVICE_ID_HASH)
    )


def vehicle_defects_response(
    make: str, model: str, year: int | None, engine: str, search_online: bool
) -> dict[str, Any]:
    result = vehicle_defect_reports(make, model, year, engine)
    if result is None:
        # A catalog entry is optional: every vehicle can still receive live
        # source candidates from the approved online research flow.
        result = {
            "catalogVersion": VEHICLE_DEFECT_CATALOG.get("catalogVersion", 1),
            "make": str(make or "").strip(),
            "model": str(model or "").strip(),
            "searchContext": {"year": year, "engine": str(engine or "").strip()},
            "vehicles": [],
            "reports": [],
            "disclaimer": (
                "Nessuna segnalazione curata ancora disponibile per questo modello. "
                "Le fonti online restano da leggere e verificare."
            ),
        }
    if search_online and defect_research_configured():
        try:
            online_research = search_defect_source_candidates(
                make, model, year, engine
            )
            result = {
                **result,
                "onlineCandidates": online_research.get("candidates", []),
                "onlineResearchFromCache": online_research.get("fromCache", False),
            }
        except (RuntimeError, ValueError, OSError, urllib.error.URLError):
            result = {
                **result,
                "onlineCandidates": [],
                "onlineResearchUnavailable": True,
            }
    return result


DEFECT_SOURCE_OFFICIAL = "NHTSA richiami/reclami ufficiali"
DEFECT_SOURCE_COMMUNITY = "Community/forum utenti da verificare"
DEFECT_SOURCE_SURVEY = "Owner reviews/survey affidabilita da verificare"

DEFECT_DATABASE: list[dict[str, Any]] = [
    {
        "brand": "Fiat",
        "aliases": ["Abarth", "Lancia"],
        "models": ["500", "595", "695", "panda", "panda hybrid", "tipo", "punto", "500x", "500l", "ypsilon", "elefantino"],
        "title": "Frizione, elettronica, mild hybrid e avantreno",
        "severity": "Media",
        "typicalKm": "60.000 - 170.000 km",
        "estimatedCost": "120 - 1800 EUR",
        "check": "Controlla frizione, servosterzo city, batteria 12V/start&stop, display, sensori, sospensioni anteriori, EGR/DPF sui diesel e richiami con telaio.",
        "evidence": "Mix database AutoStorico: richiami ufficiali dove disponibili e segnali community per modelli Fiat/Lancia/Abarth molto diffusi.",
        "sourceLabel": DEFECT_SOURCE_COMMUNITY,
        "sourceUrl": "https://www.honestjohn.co.uk/owner-reviews/",
        "recallCount": 2,
        "complaintCount": 5,
        "communitySignal": 8,
    },
    {
        "brand": "Alfa Romeo",
        "aliases": ["Alfa"],
        "models": ["giulia", "stelvio", "giulietta", "tonale", "junior", "mito", "147", "156", "159", "brera", "spider"],
        "title": "Freni, carburante, elettronica e sospensioni",
        "severity": "Alta",
        "typicalKm": "50.000 - 180.000 km",
        "estimatedCost": "180 - 2600 EUR",
        "check": "Controlla frenata, odore carburante, spie quadro, infotainment, ADAS sui modelli recenti, frizione/cambio e bracci sospensione sui modelli piu datati.",
        "evidence": "NHTSA segnala richiami/reclami per Giulia e Stelvio; Tonale/Junior hanno dati storici ancora limitati e vanno valutate con segnali community e campagne aperte.",
        "sourceLabel": DEFECT_SOURCE_OFFICIAL,
        "sourceUrl": "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
        "recallCount": 20,
        "complaintCount": 204,
        "communitySignal": 8,
    },
    {
        "brand": "Peugeot",
        "aliases": ["Peugeto", "Citroen", "Citroën", "Opel", "Vauxhall"],
        "models": ["205", "206", "207", "208", "2008", "307", "308", "3008", "407", "508", "5008", "partner", "rifter", "expert", "c3", "c4", "corsa", "astra", "mokka"],
        "title": "PureTech wet belt, BlueHDi AdBlue e elettronica",
        "severity": "Alta",
        "typicalKm": "50.000 - 180.000 km",
        "estimatedCost": "250 - 2600 EUR",
        "check": "Su PureTech controlla cinghia bagno olio e consumo olio; su diesel verifica AdBlue, NOx, EGR, DPF, turbo, frizione e storico tagliandi.",
        "evidence": "Segnali frequenti da owner reports e domande tecniche su motori Stellantis PureTech/BlueHDi; confermare sempre codice motore e manutenzione.",
        "sourceLabel": "Ask Honest John/community da verificare",
        "sourceUrl": "https://good-garage-guide.honestjohn.co.uk/askhj/",
        "recallCount": 0,
        "complaintCount": 0,
        "communitySignal": 10,
    },
    {
        "brand": "Volkswagen",
        "aliases": ["VW", "Skoda", "Seat", "Cupra"],
        "models": ["golf", "polo", "tiguan", "passat", "t-roc", "t-cross", "taigo", "touran", "caddy", "fabia", "octavia", "leon", "ibiza", "ateca"],
        "title": "DSG, infotainment, motore/diesel e ADAS",
        "severity": "Media",
        "typicalKm": "70.000 - 180.000 km",
        "estimatedCost": "180 - 2600 EUR",
        "check": "Controlla cambio DSG/meccatronica, display, sensori, EGR/AdBlue sui diesel, spie motore, freni, sospensioni e richiami gruppo VW.",
        "evidence": "NHTSA ha richiami/reclami per Golf/Tiguan; owner reports indicano controlli su DSG, elettronica e sistemi antinquinamento.",
        "sourceLabel": DEFECT_SOURCE_OFFICIAL,
        "sourceUrl": "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
        "recallCount": 19,
        "complaintCount": 311,
        "communitySignal": 8,
    },
    {
        "brand": "Audi",
        "aliases": [],
        "models": ["a1", "a3", "a4", "a5", "a6", "q2", "q3", "q5", "q7"],
        "title": "S tronic, airbag/elettronica e diesel AdBlue",
        "severity": "Media",
        "typicalKm": "70.000 - 190.000 km",
        "estimatedCost": "220 - 3500 EUR",
        "check": "Controlla S tronic, MMI, sensori, airbag, freni, AdBlue/EGR sui diesel, sospensioni e fatture manutenzione.",
        "evidence": "NHTSA mostra richiami/reclami per A3/A4; community segnala costi elevati su cambio, elettronica e diesel.",
        "sourceLabel": DEFECT_SOURCE_OFFICIAL,
        "sourceUrl": "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
        "recallCount": 3,
        "complaintCount": 86,
        "communitySignal": 7,
    },
    {
        "brand": "BMW",
        "aliases": ["Mini"],
        "models": ["serie 1", "1 series", "serie 3", "3 series", "serie 5", "x1", "x3", "x5", "mini", "cooper", "countryman"],
        "title": "Distribuzione, xDrive, elettronica e diesel",
        "severity": "Media",
        "typicalKm": "80.000 - 200.000 km",
        "estimatedCost": "250 - 4000 EUR",
        "check": "Controlla rumori catena a freddo, perdite olio, cambio automatico, xDrive, EGR/AdBlue sui diesel, sospensioni e diagnosi centraline.",
        "evidence": "NHTSA e owner reports indicano controlli su motore, alimentazione, struttura/elettronica; rischio varia molto per motore e anno.",
        "sourceLabel": DEFECT_SOURCE_OFFICIAL,
        "sourceUrl": "https://www.nhtsa.gov/nhtsa-datasets-and-apis",
        "recallCount": 4,
        "complaintCount": 117,
        "communitySignal": 8,
    },
    {
        "brand": "Toyota",
        "aliases": ["Lexus"],
        "models": ["aygo", "yaris", "corolla", "auris", "rav4", "c-hr", "chr", "prius", "hilux", "land cruiser"],
        "title": "Ibrido, batteria 12V/HV e controlli sicurezza",
        "severity": "Bassa",
        "typicalKm": "70.000 - 220.000 km",
        "estimatedCost": "120 - 3000 EUR",
        "check": "Controlla stato sistema ibrido, batteria 12V/HV, inverter, freni rigenerativi, richiami, manutenzione Toyota e ruggine su 4x4.",
        "evidence": "Survey affidabilita spesso positive, ma su usato ibrido vanno verificati batteria, garanzia e storico ufficiale.",
        "sourceLabel": DEFECT_SOURCE_SURVEY,
        "sourceUrl": "https://www.whatcar.com/news/what-car-reliability-survey-what-does-it-reveal-about-owners-and-their-cars/n19298",
        "recallCount": 1,
        "complaintCount": 4,
        "communitySignal": 5,
    },
    {
        "brand": "Ford",
        "aliases": [],
        "models": ["fiesta", "focus", "kuga", "puma", "ecosport", "mondeo", "transit", "tourneo"],
        "title": "EcoBoost wet belt, diesel e cambio",
        "severity": "Alta",
        "typicalKm": "80.000 - 220.000 km",
        "estimatedCost": "250 - 3500 EUR",
        "check": "Verifica cinghia bagno olio sui motori interessati, pressione olio, raffreddamento, frizione/cambio, EGR/DPF sui diesel e uso lavoro sui van.",
        "evidence": "Segnali tecnici e community evidenziano controlli prioritari su EcoBoost e van usati.",
        "sourceLabel": "Ask Honest John/community da verificare",
        "sourceUrl": "https://good-garage-guide.honestjohn.co.uk/askhj/",
        "recallCount": 0,
        "complaintCount": 0,
        "communitySignal": 9,
    },
]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def defect_entry_matches(entry: dict[str, Any], brand: str, model: str) -> bool:
    brand_text = normalize_text(brand)
    model_text = normalize_text(model)
    brand_names = [entry["brand"], *entry.get("aliases", [])]
    return any(normalize_text(name) in brand_text for name in brand_names) and any(
        normalize_text(model_name) in model_text for model_name in entry["models"]
    )


def public_defect_entry(entry: dict[str, Any], brand: str, model: str, km: int) -> dict[str, Any]:
    item = {
        "brand": entry["brand"],
        "brandAliases": entry.get("aliases", []),
        "models": entry["models"],
        "title": entry["title"],
        "severity": entry["severity"],
        "typicalKm": entry["typicalKm"],
        "estimatedCost": entry["estimatedCost"],
        "check": entry["check"],
        "evidence": entry["evidence"],
        "sourceLabel": entry["sourceLabel"],
        "sourceUrl": entry["sourceUrl"],
        "recallCount": entry.get("recallCount", 0),
        "complaintCount": entry.get("complaintCount", 0),
        "communitySignal": entry.get("communitySignal", 0),
    }
    if km >= 150000 and item["severity"] != "Alta":
        item["evidence"] += " Chilometraggio elevato: aumentare attenzione su manutenzione documentata e prova su strada."
    item["requestedVehicle"] = {"brand": brand, "model": model, "km": km}
    return item


def lookup_defects(query: dict[str, list[str]]) -> dict[str, Any]:
    brand = (query.get("brand") or query.get("make") or [""])[0]
    model = (query.get("model") or [""])[0]
    km = int(parse_float((query.get("km") or ["0"])[0], 0))
    matches = [entry for entry in DEFECT_DATABASE if defect_entry_matches(entry, brand, model)]
    if not matches:
        brand_text = normalize_text(brand)
        matches = [
            entry
            for entry in DEFECT_DATABASE
            if any(normalize_text(name) in brand_text for name in [entry["brand"], *entry.get("aliases", [])])
        ][:3]
    if not matches:
        matches = [
            {
                "brand": brand or "Generico",
                "aliases": [],
                "models": [model or "modello non indicato"],
                "title": "Controllo generico pre-acquisto",
                "severity": "Media",
                "typicalKm": "variabile",
                "estimatedCost": "variabile",
                "check": "Controlla storico tagliandi, diagnosi OBD, prova a freddo, frizione/cambio, freni, sospensioni, perdite, richiami VIN e documenti.",
                "evidence": "Nessuna scheda precisa trovata: AutoStorico restituisce una checklist prudente da verificare in officina.",
                "sourceLabel": "Checklist AutoStorico",
                "sourceUrl": "",
                "recallCount": 0,
                "complaintCount": 0,
                "communitySignal": 4,
            }
        ]
    defects = [public_defect_entry(entry, brand, model, km) for entry in matches]
    return {
        "defects": defects,
        "count": len(defects),
        "source": "AutoStorico defects API",
        "disclaimer": "Dati indicativi basati su richiami, reclami pubblici, owner reports e community: non sostituiscono diagnosi o verifica tecnica.",
    }


class AutoStoricoApi(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        request_path = parsed_url.path.rstrip("/") or "/"
        if request_path == "/health":
            configured_providers = {
                "brave": bool(BRAVE_SEARCH_API_KEY),
                "serpapi": bool(SERPAPI_API_KEY),
                "google_cse": bool(GOOGLE_CSE_ENABLED and GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID),
            }
            self.send_json(
                {
                    "ok": True,
                    "service": "autostorico-value-api",
                    "supportedInputs": ["fuelType", "engineDisplacement"],
                    "marketSearchConfigured": any(configured_providers.values()),
                    "configuredProviders": configured_providers,
                    "premiumVerificationConfigured": premium_verification_configured(),
                    "playIntegrityConfigured": play_integrity_configured(),
                    "playIntegrityRequired": PLAY_INTEGRITY_REQUIRED,
                    "playIntegrityMinVersionCode": PLAY_INTEGRITY_MIN_VERSION_CODE,
                    "vehicleDefectCatalogReady": bool(VEHICLE_DEFECT_CATALOG.get("vehicles")),
                    "defectResearchConfigured": defect_research_configured(),
                }
            )
            return
        if request_path in {"/api/defects", "/defects"}:
            self.send_json(lookup_defects(urllib.parse.parse_qs(parsed_url.query)))
            return
        if request_path == "/api/defect-catalog-status":
            self.send_json(catalog_update_status())
            return
        if request_path == "/api/vehicle-defects":
            query = urllib.parse.parse_qs(parsed_url.query)
            make = query.get("make", [""])[0]
            model = query.get("model", [""])[0]
            year = catalog_year_value(query.get("year", [""])[0]) or None
            engine = query.get("engine", [""])[0]
            search_online = query.get("searchOnline", ["0"])[0] == "1"
            if search_online:
                self.send_json(
                    {
                        "error": "gold_required",
                        "message": "La ricerca online Difetti Gold richiede verifica server-side.",
                    },
                    status=402,
                )
                return
            self.send_json(
                vehicle_defects_response(make, model, year, engine, search_online=False)
            )
            return
        if request_path == "/api/admin/defect-source-candidates":
            auth = self.headers.get("Authorization", "")
            if not DEFECT_RESEARCH_API_KEY or auth != f"Bearer {DEFECT_RESEARCH_API_KEY}":
                self.send_json({"error": "unauthorized"}, status=401)
                return
            query = urllib.parse.parse_qs(parsed_url.query)
            try:
                self.send_json(
                    search_defect_source_candidates(
                        query.get("make", [""])[0],
                        query.get("model", [""])[0],
                        catalog_year_value(query.get("year", [""])[0]) or None,
                        query.get("engine", [""])[0],
                    )
                )
            except (RuntimeError, ValueError) as exc:
                self.send_json(
                    {"error": "research_unavailable", "detail": str(exc)},
                    status=503,
                )
            return
        self.send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        request_path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if request_path not in {
            "/api/vehicle-value",
            "/api/premium/verify",
            "/api/developer/entitlement",
            "/api/vehicle-defects",
        }:
            self.send_json({"error": "not_found"}, status=404)
            return

        auth = self.headers.get("Authorization", "")
        if request_path == "/api/premium/verify":
            if auth and PREMIUM_API_KEY and auth != f"Bearer {PREMIUM_API_KEY}":
                self.send_json({"error": "unauthorized"}, status=401)
                return
        elif auth and API_KEY and auth != f"Bearer {API_KEY}":
            self.send_json({"error": "unauthorized"}, status=401)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                self.send_json({"error": "invalid_request"}, status=400)
                return
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Payload must be an object")
            if request_path == "/api/premium/verify":
                client_id = (
                    self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or self.client_address[0]
                )
                if not can_run_premium_verification(client_id):
                    self.send_json(
                        {
                            "error": "rate_limited",
                            "retryAfterSeconds": MARKET_RATE_WINDOW_SECONDS,
                        },
                        status=429,
                    )
                    return
                integrity = verify_play_integrity(payload)
                if not integrity.get("ok"):
                    self.send_json(
                        {
                            "active": False,
                            "isTrial": False,
                            "message": integrity.get("message")
                            or "Controllo sicurezza non superato.",
                        }
                    )
                    return
                product_id = str(payload.get("productId") or "").strip()
                product_type = str(payload.get("productType") or "").strip().lower()
                if product_type in {"inapp", "product", "one_time"}:
                    verification = verify_google_play_product(
                        str(payload.get("purchaseToken") or "").strip(),
                        product_id,
                    )
                else:
                    verification = verify_google_play_subscription(
                        str(payload.get("purchaseToken") or "").strip(),
                        product_id,
                    )
                self.send_json(verification)
                return
            if request_path == "/api/developer/entitlement":
                client_id = (
                    self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or self.client_address[0]
                )
                if not can_run_premium_verification(client_id):
                    self.send_json({"active": False}, status=429)
                    return
                device_id_hash = str(payload.get("deviceIdHash") or "").strip().lower()
                active = developer_device_is_authorized(device_id_hash)
                # Temporary enrollment diagnostic for the Play-signed owner app.
                # It records only an irreversible SHA-256 value, never a device id.
                if (
                    not active
                    and re.fullmatch(r"[a-f0-9]{64}", device_id_hash)
                ):
                    print(f"developer_entitlement_candidate={device_id_hash}", flush=True)
                self.send_json({"active": active})
                return
            if request_path == "/api/vehicle-defects":
                client_id = (
                    self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or self.client_address[0]
                )
                if not can_run_market_search(client_id):
                    self.send_json(
                        {
                            "error": "rate_limited",
                            "retryAfterSeconds": MARKET_RATE_WINDOW_SECONDS,
                        },
                        status=429,
                    )
                    return
                entitlement = verify_defect_online_entitlement(payload)
                if not entitlement.get("ok"):
                    self.send_json(
                        {
                            "error": "gold_required",
                            "message": entitlement.get("message")
                            or "Difetti Gold non verificata.",
                        },
                        status=int(entitlement.get("status") or 402),
                    )
                    return
                make = str(payload.get("make") or "").strip()
                model = str(payload.get("model") or "").strip()
                year = catalog_year_value(payload.get("year")) or None
                engine = str(payload.get("engine") or "").strip()
                self.send_json(
                    vehicle_defects_response(
                        make, model, year, engine, search_online=True
                    )
                )
                return
            cache_key = market_cache_key(payload)
            estimate = cached_market_estimate(cache_key)
            if estimate is None:
                client_id = (
                    self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                    or self.client_address[0]
                )
                if not can_run_market_search(client_id):
                    self.send_json(
                        {"error": "rate_limited", "retryAfterSeconds": MARKET_RATE_WINDOW_SECONDS},
                        status=429,
                    )
                    return
                estimate = estimate_vehicle_value(payload)
                cache_market_estimate(cache_key, estimate)
            self.send_json({"estimate": estimate})
        except Exception as exc:
            self.send_json({"error": "bad_request", "detail": str(exc)}, status=400)

    def send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), AutoStoricoApi)
    print(f"AutoStorico API avviata su http://{HOST}:{PORT}")
    print("Endpoint: POST /api/vehicle-value")
    server.serve_forever()


if __name__ == "__main__":
    main()

