from __future__ import annotations

import re
from typing import Any

import server

_ORIGINAL_PLATE_INFO_LOOKUP = server.plate_info_lookup

_BRANDS = [
    "ALFA ROMEO", "ASTON MARTIN", "LAND ROVER", "MERCEDES-BENZ",
    "MERCEDES", "VOLKSWAGEN", "CITROEN", "CITROËN", "RENAULT",
    "PEUGEOT", "PORSCHE", "TOYOTA", "NISSAN", "HYUNDAI", "MITSUBISHI",
    "MASERATI", "LANCIA", "DACIA", "SKODA", "ŠKODA", "SUBARU",
    "SUZUKI", "JAGUAR", "VOLVO", "AUDI", "BMW", "FIAT", "FORD",
    "HONDA", "JEEP", "KIA", "LEXUS", "MAZDA", "MINI", "OPEL",
    "SEAT", "SMART", "TESLA", "CUPRA", "DS",
]

_STOP_WORDS = {
    "AUTO", "USATA", "USATO", "VENDITA", "TARGA", "KM", "CHILOMETRI",
    "PREZZO", "EURO", "ANNUNCIO", "AUTOVETTURA", "VEICOLO", "CAR",
}


def _pretty_brand(value: str) -> str:
    if value == "CITROËN":
        return "Citroën"
    if value == "ŠKODA":
        return "Škoda"
    return " ".join(part.capitalize() for part in value.replace("-", " ").split())


def _extract_vehicle_from_hints(hints: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(str(item.get("title") or "") for item in hints[:12])
    compact = re.sub(r"\s+", " ", text).strip()
    upper = compact.upper()
    result: dict[str, Any] = {
        "vehicleType": "Auto",
        "make": "",
        "model": "",
        "firstRegistration": "",
        "fuelType": "",
        "engineDisplacement": "",
        "powerKw": None,
        "powerCv": None,
        "provisional": True,
    }

    found_brand = ""
    brand_pos = -1
    for brand in sorted(_BRANDS, key=len, reverse=True):
        pos = upper.find(brand)
        if pos >= 0:
            found_brand = brand
            brand_pos = pos
            result["make"] = _pretty_brand(brand)
            break

    year_match = re.search(r"\b(19[8-9]\d|20[0-3]\d)\b", compact)
    if year_match:
        result["firstRegistration"] = year_match.group(1)

    if re.search(r"\b(DIESEL|GASOLIO|TDI|JTD|MJET|MULTIJET|DCI|HDI|CDI)\b", upper):
        result["fuelType"] = "Diesel"
    elif re.search(r"\b(BENZINA|PETROL|TSI|TFSI|MPI)\b", upper):
        result["fuelType"] = "Benzina"
    elif re.search(r"\b(PHEV|HYBRID|IBRIDA|IBRIDO|HEV)\b", upper):
        result["fuelType"] = "Ibrida"
    elif re.search(r"\b(ELETTRICA|ELETTRICO|ELECTRIC|BEV)\b", upper):
        result["fuelType"] = "Elettrica"
    elif re.search(r"\bGPL\b", upper):
        result["fuelType"] = "Benzina/GPL"
    elif re.search(r"\b(METANO|CNG)\b", upper):
        result["fuelType"] = "Benzina/Metano"

    cc = re.search(r"\b(\d{3,4})\s*(?:CC|CM3|CM³)\b", upper)
    if cc:
        value = int(cc.group(1))
        if 500 <= value <= 8000:
            result["engineDisplacement"] = str(value)

    kw = re.search(r"\b(\d{2,3}(?:[\.,]\d+)?)\s*KW\b", upper)
    if kw:
        try:
            value = float(kw.group(1).replace(",", "."))
            if 15 <= value <= 1000:
                result["powerKw"] = int(value) if value.is_integer() else value
                result["powerCv"] = round(value * 1.35962)
        except ValueError:
            pass

    if found_brand and brand_pos >= 0:
        tail = compact[brand_pos + len(found_brand):].strip(" -–—:|,")
        tokens = re.split(r"\s+", tail)
        model_tokens: list[str] = []
        for token in tokens:
            cleaned = token.strip(" -–—:|,.;()[]{}").upper()
            if not cleaned:
                continue
            if cleaned in _STOP_WORDS:
                break
            if re.fullmatch(r"(?:19|20)\d{2}", cleaned):
                break
            if re.fullmatch(r"\d+[\.,]?\d*€?", cleaned):
                break
            if cleaned in {"DIESEL", "BENZINA", "GPL", "METANO", "IBRIDA", "HYBRID", "ELETTRICA"}:
                break
            model_tokens.append(token.strip(" -–—:|,.;()[]{}"))
            if len(model_tokens) >= 4:
                break
        model = " ".join(model_tokens).strip()
        if model and len(model) <= 40:
            result["model"] = model

    return result


def _merge_results(target: list[dict[str, Any]], found: list[dict[str, Any]], seen: set[str]) -> None:
    for item in found:
        url = str(item.get("url") or "")
        title = str(item.get("title") or "")
        key = url or title
        if not key or key in seen:
            continue
        seen.add(key)
        target.append(item)


def _more_plate_hints(plate: str, diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    payload: dict[str, Any] = {"brand": "", "model": ""}
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    queries = [
        f'"{plate}"',
        f'"{plate}" auto',
        f'"{plate}" veicolo',
        f'"{plate}" marca modello',
        f'"{plate}" cilindrata kW',
        f'"{plate}" usato',
    ]

    for query in queries:
        if server.BRAVE_SEARCH_API_KEY:
            try:
                brave = server.brave_market_search(query, payload, diagnostics)
                _merge_results(merged, brave, seen)
            except Exception as exc:
                diagnostics.setdefault("errors", []).append({"provider": "brave", "error": str(exc)[:160]})

        if not merged and server.tavily_market_search_available():
            try:
                tavily = server.tavily_market_search(query, payload, diagnostics)
                _merge_results(merged, tavily, seen)
            except Exception as exc:
                diagnostics.setdefault("errors", []).append({"provider": "tavily", "error": str(exc)[:160]})

        if len(merged) >= 12:
            break

    return merged[:12]


def enhanced_plate_info_lookup(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    status, payload = _ORIGINAL_PLATE_INFO_LOOKUP(query)
    if status != 200 or not payload.get("ok"):
        return status, payload

    plate = str(payload.get("plate") or "")
    base_hints = payload.get("webHints") if isinstance(payload.get("webHints"), list) else []
    hints = [item for item in base_hints if isinstance(item, dict)]
    diagnostics: dict[str, Any] = {"providers": [], "errors": []}

    if plate:
        extra = _more_plate_hints(plate, diagnostics)
        existing = {str(item.get("url") or item.get("title") or "") for item in hints}
        for item in extra:
            key = str(item.get("url") or item.get("title") or "")
            if not key or key in existing:
                continue
            hints.append({
                "source": str(item.get("source") or "Fonte web"),
                "title": str(item.get("title") or "")[:180],
                "url": str(item.get("url") or ""),
                "year": item.get("year"),
                "km": item.get("km"),
            })
            existing.add(key)

    vehicle = _extract_vehicle_from_hints(hints)
    useful = any(
        str(vehicle.get(key) or "").strip()
        for key in ("make", "model", "firstRegistration", "fuelType", "engineDisplacement", "powerKw")
    )

    payload["webHints"] = hints[:12]
    payload["vehicle"] = vehicle
    payload["status"] = "provisional_vehicle_data" if useful else payload.get("status", "no_public_match")
    payload["configuredProviders"] = {
        "brave": bool(server.BRAVE_SEARCH_API_KEY),
        "tavily": server.tavily_market_search_available(),
    }
    payload["note"] = (
        "I dati preliminari derivano da Brave Search API e Tavily quando configurati, "
        "incrociando risultati pubblici. Le verifiche ufficiali restano separate e richiedono "
        "il CAPTCHA del portale quando previsto."
    )
    if diagnostics["errors"]:
        payload["diagnostics"] = diagnostics
    return 200, payload


server.plate_info_lookup = enhanced_plate_info_lookup

if __name__ == "__main__":
    server.main()
