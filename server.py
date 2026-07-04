from __future__ import annotations

import json
import math
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


API_KEY = os.environ.get("AUTOSTORICO_API_KEY", "autostorico-test-key")
HOST = os.environ.get("AUTOSTORICO_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("AUTOSTORICO_API_PORT", "8088"))


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
                return 2500
            if normalized_condition == "Buono":
                return 1500
            return 900
        if is_panda_classic or is_economy:
            if normalized_condition == "Ottimo":
                return 800
            if normalized_condition == "Buono":
                return 450
            return 250
        if is_premium_or_rare:
            if normalized_condition == "Ottimo":
                return 1800
            if normalized_condition == "Buono":
                return 1100
            return 650
        return 350 if normalized_condition == "Sufficiente" else 650

    if age >= 15:
        if normalized_condition == "Ottimo":
            return 1600 if is_premium_or_rare else 900
        if normalized_condition == "Buono":
            return 1000 if is_premium_or_rare else 650
        return 650 if is_premium_or_rare else 350

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

    age_factor = math.pow(0.86 if is_moto else 0.84, age)
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
    average = max(floor_value, raw_value)
    spread = 0.26 if year is None else 0.28 if age >= 20 else 0.16
    min_value = max(floor_value * 0.75, average * (1 - spread))
    max_value = max(min_value + 200, average * (1 + spread))

    has_details = bool(fuel_type and gearbox and condition and previous_owners)
    confidence = (
        "Alta: anno, km, stato e dettagli veicolo ricevuti dall'app."
        if year is not None and km > 0 and has_details
        else "Media: per aumentare attendibilita compila anno, km, stato, gomme, aria condizionata, proprietari, cambio, alimentazione e lavori."
    )

    return {
        "minValue": round_to_hundreds(min_value),
        "averageValue": round_to_hundreds(average),
        "maxValue": round_to_hundreds(max_value),
        "confidence": confidence,
        "method": "API AutoStorico: stima server basata su anno, km, marca/modello, allestimento, stato, gomme, aria condizionata, proprietari, storico e documenti. Confronto predisposto per banche dati/listini e annunci pubblici autorizzati.",
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

