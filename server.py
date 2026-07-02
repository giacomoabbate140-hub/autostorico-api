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


def estimated_new_value(vehicle_type: str, brand: str, model: str) -> float:
    if vehicle_type.lower() == "moto":
        return 7500

    brand_model = f"{brand} {model}".lower()
    premium = ["audi", "bmw", "mercedes", "lexus", "tesla", "volvo"]
    upper = ["alfa romeo", "mini", "jeep", "cupra", "land rover", "jaguar"]
    economy = ["fiat", "dacia", "citroen", "renault", "peugeot", "opel", "ford", "hyundai", "kia"]

    if any(name in brand_model for name in premium):
        return 32000
    if any(name in brand_model for name in upper):
        return 26000
    if any(name in brand_model for name in economy):
        return 19000
    return 22000


def estimate_vehicle_value(payload: dict[str, Any]) -> dict[str, Any]:
    vehicle_type = str(payload.get("vehicleType") or "Auto").strip()
    brand = str(payload.get("brand") or "").strip()
    model = str(payload.get("model") or "").strip()
    km = parse_float(payload.get("km"))
    year = parse_year(payload.get("firstRegistrationDate"))

    current_year = 2026
    age = 6 if year is None else max(0, min(30, current_year - year))
    base_value = estimated_new_value(vehicle_type, brand, model)
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

    raw_value = base_value * age_factor * mileage_factor * history_factor
    floor_value = 700 if is_moto else 1200
    average = max(floor_value, raw_value)
    spread = 0.22 if year is None else 0.15
    min_value = max(floor_value, average * (1 - spread))
    max_value = max(min_value + 300, average * (1 + spread))

    confidence = (
        "Alta: dati completi ricevuti dall'app."
        if year is not None and km > 0
        else "Media: mancano anno o km precisi."
    )

    return {
        "minValue": round_to_hundreds(min_value),
        "averageValue": round_to_hundreds(average),
        "maxValue": round_to_hundreds(max_value),
        "confidence": confidence,
        "method": "API AutoStorico: stima server basata su anno, km, marca/modello, storico e documenti. Pronta per collegamento a banca dati esterna autorizzata.",
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
