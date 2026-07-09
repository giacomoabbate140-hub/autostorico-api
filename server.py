from __future__ import annotations

import json
import math
import os
import re
import html
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


API_KEY = os.environ.get("AUTOSTORICO_API_KEY", "autostorico-test-key")
HOST = os.environ.get("AUTOSTORICO_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("AUTOSTORICO_API_PORT", "8088"))
GOOGLE_CSE_API_KEY = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID", "").strip()
GOOGLE_CSE_ENABLED = os.environ.get("AUTOSTORICO_GOOGLE_CSE_ENABLED", "0") == "1"
BRAVE_SEARCH_API_KEY = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
SERPAPI_API_KEY = os.environ.get("SERPAPI_API_KEY", "").strip()
MARKET_SEARCH_ENABLED = os.environ.get("AUTOSTORICO_MARKET_SEARCH", "1") != "0"
MARKET_SITES = [
    ("AutoScout24", "autoscout24.it"),
    ("Subito Motori", "subito.it"),
    ("Automobile.it", "automobile.it"),
    ("Quattroruote", "quattroruote.it"),
    ("AutoUncle", "autouncle.it"),
    ("Trovit Auto", "auto.trovit.it"),
    ("Bakeca Motori", "bakeca.it"),
    ("Moto.it/Automoto", "automoto.it"),
]


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
    if brand and brand not in cleaned:
        return False
    if model:
        model_tokens = [token for token in re.split(r"\s+", model) if len(token) > 1]
        if model_tokens and not all(token in cleaned for token in model_tokens):
            return False
    return True


def listing_from_search_item(item: dict[str, Any], fallback_source: str = "Fonte web", payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or item.get("description") or "")
    link = str(item.get("link") or item.get("url") or item.get("product_link") or "")
    if not link:
        return None
    if not is_market_url(link):
        return None
    if payload is not None and not is_relevant_listing_text(f"{title} {snippet} {link}", payload):
        return None
    item_text = json.dumps(item, ensure_ascii=False)
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
    center = median(prices)
    lower_limit = max(300.0, center * 0.55)
    upper_limit = center * 1.65
    filtered = [
        item
        for item in listings
        if lower_limit <= float(item.get("price") or 0) <= upper_limit
    ]
    filtered_prices = [float(item["price"]) for item in filtered]
    if len(filtered_prices) < 2:
        return None, filtered
    source_average = median(filtered_prices)
    if internal_average > 0:
        blended = (source_average * 0.90) + (internal_average * 0.10)
    else:
        blended = source_average
    return blended, filtered


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
    average = market_average if market_average is not None else internal_average
    spread = 0.26 if year is None else 0.28 if age >= 20 else 0.16
    min_value = max(floor_value * 0.75, average * (1 - spread))
    max_value = max(min_value + 200, average * (1 + spread))

    has_details = bool(fuel_type and engine_cc and gearbox and condition and previous_owners)
    matched_count = len(filtered_listings)
    market_based = matched_count >= 2
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
        "Valore calcolato partendo da annunci/fonti mercato compatibili; i dati del veicolo correggono solo leggermente il range."
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
        "matchedListings": matched_count,
        "sourcesUsed": source_names,
        "marketBased": market_based,
        "serverOnline": True,
        "marketSearchConfigured": market_configured,
        "configuredProviders": market_diagnostics.get("configuredProviders", {}),
        "sampleListings": filtered_listings[:5],
    }
    if payload.get("debug") is True:
        response["marketDiagnostics"] = market_diagnostics
    return response


class AutoStoricoApi(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        request_path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
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
                }
            )
            return
        self.send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        request_path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if request_path != "/api/vehicle-value":
            self.send_json({"error": "not_found"}, status=404)
            return

        auth = self.headers.get("Authorization", "")
        expected = f"Bearer {API_KEY}"
        if API_KEY and auth != expected:
            self.send_json({"error": "unauthorized"}, status=401)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(raw_body or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Payload must be an object")
            estimate = estimate_vehicle_value(payload)
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

