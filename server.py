from __future__ import annotations

import json
import math
import os
import re
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


API_KEY = os.environ.get("AUTOSTORICO_API_KEY", "autostorico-test-key")
HOST = os.environ.get("AUTOSTORICO_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("AUTOSTORICO_API_PORT", "8088"))
GOOGLE_CSE_API_KEY = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID", "").strip()
MARKET_SEARCH_ENABLED = os.environ.get("AUTOSTORICO_MARKET_SEARCH", "1") != "0"
MARKET_SITES = [
    ("AutoScout24", "autoscout24.it"),
    ("Subito Motori", "subito.it"),
    ("Automobile.it", "automobile.it"),
    ("Moto.it/Automoto", "automoto.it"),
]


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, str):
            value = value.replace(".", "").replace(",", ".")
        return float(value)
    except (TypeError, ValueError):
        return default


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
    brand = str(payload.get("brand") or "").strip()
    model = str(payload.get("model") or "").strip()
    trim = str(payload.get("trim") or "").strip()
    km = int(parse_float(payload.get("km")))
    query_core = " ".join(part for part in [brand, model, trim] if part)
    if year:
        query_core = f"{query_core} {year}"
    if km > 0:
        rounded_km = int(round(km / 10000) * 10000)
        query_core = f"{query_core} {rounded_km} km"
    if not query_core.strip():
        return []
    return [f"{query_core} prezzo site:{domain}" for _, domain in MARKET_SITES]


def google_market_search(query: str) -> list[dict[str, Any]]:
    if not GOOGLE_CSE_API_KEY or not GOOGLE_CSE_ID:
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
        title = str(item.get("title") or "")
        snippet = str(item.get("snippet") or "")
        link = str(item.get("link") or "")
        price = extract_price(f"{title} {snippet}")
        if price is None:
            continue
        source_name = next(
            (name for name, domain in MARKET_SITES if domain in link),
            "Fonte web",
        )
        results.append(
            {
                "source": source_name,
                "title": title[:140],
                "url": link,
                "price": price,
            }
        )
    return results


def fetch_market_sources(payload: dict[str, Any], year: int | None) -> list[dict[str, Any]]:
    if not MARKET_SEARCH_ENABLED:
        return []
    listings: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in build_market_queries(payload, year):
        try:
            for listing in google_market_search(query):
                url = str(listing.get("url") or "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                listings.append(listing)
        except Exception:
            continue
    return listings[:20]


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
    if len(filtered_prices) < 3:
        return None, filtered
    source_average = median(filtered_prices)
    if internal_average > 0:
        blended = (source_average * 0.70) + (internal_average * 0.30)
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


def estimated_new_value(vehicle_type: str, brand: str, model: str, trim: str = "") -> float:
    if vehicle_type.lower() == "moto":
        return 7500

    brand_model = f"{brand} {model} {trim}".lower()
    premium = ["audi", "bmw", "mercedes", "lexus", "tesla", "volvo"]
    upper = ["alfa romeo", "mini", "jeep", "cupra", "land rover", "jaguar"]
    economy = ["fiat", "dacia", "citroen", "renault", "peugeot", "opel", "ford", "hyundai", "kia"]

    if "panda" in brand_model:
        return 14500
    if any(name in brand_model for name in ["punto", "seicento", "cinquecento"]):
        return 13500
    if any(name in brand_model for name in premium):
        return 32000
    if any(name in brand_model for name in upper):
        return 26000
    if any(name in brand_model for name in economy):
        return 17500
    return 22000


def normalize_previous_owners(value: str) -> str:
    cleaned = value.strip().lower()
    if 'piu' in cleaned or 'oltre' in cleaned or '2+' in cleaned:
        return 'Piu di 2 proprietari'
    if cleaned.startswith('2'):
        return '2 proprietari'
    return '1 proprietario'


def vehicle_detail_factor(fuel_type: str, gearbox: str, trim: str, condition: str, tires_changed: bool = False, tire_type: str = '', air_conditioning_ok: bool = False, previous_owners: str = '1 proprietario') -> float:
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
    if "hybrid" in fuel or "ibrid" in fuel or "elettr" in fuel:
        factor += 0.04
    elif "diesel" in fuel:
        factor -= 0.02

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
    is_panda_classic = "panda" in brand_model
    is_collectible_panda = is_panda_classic and any(
        name in brand_model for name in ["4x4", "sisley", "selecta"]
    )

    if is_moto:
        if age >= 25:
            return 350 if normalized_condition == "Sufficiente" else 550
        return 500 if normalized_condition == "Sufficiente" else 700

    if age >= 25:
        if is_collectible_panda:
            if normalized_condition == "Ottimo":
                return 6000
            if normalized_condition == "Buono":
                return 3500
            return 1800
        if is_panda_classic or is_economy:
            if normalized_condition == "Ottimo":
                return 1400
            if normalized_condition == "Buono":
                return 800
            return 400
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
    brand = str(payload.get("brand") or "").strip()
    model = str(payload.get("model") or "").strip()
    km = parse_float(payload.get("km"))
    fuel_type = str(payload.get("fuelType") or "").strip()
    gearbox = str(payload.get("gearbox") or "").strip()
    trim = str(payload.get("trim") or "").strip()
    condition = str(payload.get("condition") or "Buono").strip()
    tires_changed = bool(payload.get("tiresChanged") is True)
    tire_type = str(payload.get("tireType") or "").strip()
    air_conditioning_ok = bool(payload.get("airConditioningOk") is True)
    previous_owners = str(payload.get("previousOwners") or "1 proprietario").strip()
    year = parse_year(payload.get("firstRegistrationDate"))

    current_year = 2026
    age = 6 if year is None else max(0, min(30, current_year - year))
    base_value = estimated_new_value(vehicle_type, brand, model, trim)
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

    detail_factor = vehicle_detail_factor(fuel_type, gearbox, trim, condition, tires_changed, tire_type, air_conditioning_ok, previous_owners)
    raw_value = base_value * age_factor * mileage_factor * history_factor * detail_factor
    floor_value = market_floor_value(vehicle_type, brand, model, trim, condition, age)
    internal_average = max(floor_value, raw_value)
    listings = fetch_market_sources(payload, year)
    market_average, filtered_listings = market_estimate_from_sources(
        listings,
        internal_average,
    )
    average = market_average if market_average is not None else internal_average
    spread = 0.26 if year is None else 0.28 if age >= 20 else 0.16
    min_value = max(floor_value * 0.75, average * (1 - spread))
    max_value = max(min_value + 200, average * (1 + spread))

    has_details = bool(fuel_type and gearbox and condition and previous_owners)
    matched_count = len(filtered_listings)
    source_names = sorted({str(item.get("source") or "Fonte web") for item in filtered_listings})
    confidence = (
        f"Alta: valore confrontato con {matched_count} annunci/fonti web compatibili."
        if matched_count >= 8
        else f"Media: valore confrontato con {matched_count} annunci/fonti web compatibili."
        if matched_count >= 3
        else "Media: fonti web non configurate o insufficienti; usata stima interna da vendita privata."
        if year is not None and km > 0 and has_details
        else "Media: compila anno, km, stato, gomme, aria condizionata, proprietari, cambio, alimentazione e lavori."
    )
    method = (
        "API AutoStorico: valore di vendita tra privati calcolato combinando fonti web/listini configurati "
        "con anno, km, marca/modello, allestimento, stato, gomme, aria condizionata, proprietari, storico lavori, revisioni e documenti."
        if matched_count >= 3
        else "API AutoStorico: valore di vendita tra privati calcolato con stima interna perche le fonti web autorizzate non sono ancora configurate o non hanno prodotto abbastanza annunci compatibili."
    )

    return {
        "minValue": round_to_hundreds(min_value),
        "averageValue": round_to_hundreds(average),
        "maxValue": round_to_hundreds(max_value),
        "confidence": confidence,
        "method": method,
        "marketType": "vendita_privata",
        "matchedListings": matched_count,
        "sourcesUsed": source_names,
        "marketSearchConfigured": bool(GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID),
        "sampleListings": filtered_listings[:5],
    }


class AutoStoricoApi(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json({"ok": True, "service": "autostorico-value-api"})
            return
        self.send_json({"error": "not_found"}, status=404)

    def do_POST(self) -> None:
        if self.path != "/api/vehicle-value":
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

