from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import server

_ORIGINAL_PLATE_INFO_LOOKUP = server.plate_info_lookup
_ORIGINAL_BRAVE_MARKET_SEARCH = server.brave_market_search
_ORIGINAL_TAVILY_MARKET_SEARCH = server.tavily_market_search
_ORIGINAL_SEARCH_DEFECT_SOURCE_CANDIDATES = server.search_defect_source_candidates
_ORIGINAL_DO_GET = server.AutoStoricoApi.do_GET

_PROVIDER_DIAGNOSTICS_LOCK = threading.Lock()
_PROVIDER_DIAGNOSTICS: dict[str, dict[str, Any]] = {
    "tavily": {
        "lastStatus": None,
        "lastResults": None,
        "lastSuccessAt": "",
        "lastError": "",
        "lastOperation": "",
        "elapsedMs": None,
    },
    "brave": {
        "lastStatus": None,
        "lastResults": None,
        "lastSuccessAt": "",
        "lastError": "",
        "lastOperation": "",
        "elapsedMs": None,
    },
}

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _record_provider_result(
    provider: str,
    *,
    status: int,
    result_count: int | None,
    operation: str,
    elapsed_ms: int,
    error: str = "",
) -> None:
    if provider not in _PROVIDER_DIAGNOSTICS:
        return
    with _PROVIDER_DIAGNOSTICS_LOCK:
        item = _PROVIDER_DIAGNOSTICS[provider]
        item["lastStatus"] = status
        item["lastResults"] = result_count
        item["lastOperation"] = operation
        item["elapsedMs"] = elapsed_ms
        item["lastError"] = error[:180]
        if 200 <= status < 300:
            item["lastSuccessAt"] = _utc_now_iso()


def _provider_message(
    label: str,
    *,
    configured: bool,
    available: bool,
    last_status: int | None,
    last_results: int | None,
) -> str:
    if not configured:
        return f"{label}: NON CONFIGURATO"
    if last_status is not None and 200 <= last_status < 300:
        count = max(0, int(last_results or 0))
        return f"{label}: OK — {count} risultati trovati"
    if last_status is not None and last_status >= 400:
        return f"{label}: ERRORE — ultima richiesta non riuscita"
    if not available:
        return f"{label}: LIMITE RAGGIUNTO O TEMPORANEAMENTE NON DISPONIBILE"
    return f"{label}: PRONTO — nessuna ricerca registrata"


def provider_diagnostics_payload() -> dict[str, Any]:
    today = server._utc_day_key()
    tavily_configured = bool(server.TAVILY_ENABLED and server.TAVILY_API_KEY)
    brave_configured = bool(server.BRAVE_SEARCH_API_KEY)
    tavily_available = server.tavily_market_search_available()
    brave_available = server.brave_search_available()

    with _PROVIDER_DIAGNOSTICS_LOCK:
        tavily_last = dict(_PROVIDER_DIAGNOSTICS["tavily"])
        brave_last = dict(_PROVIDER_DIAGNOSTICS["brave"])

    tavily = {
        "configured": tavily_configured,
        "available": tavily_available,
        "usedToday": server.TAVILY_DAILY_USAGE.get(today, 0),
        "dailyLimit": server.TAVILY_DAILY_LIMIT,
        **tavily_last,
    }
    brave = {
        "configured": brave_configured,
        "available": brave_available,
        "usedToday": server.BRAVE_DAILY_USAGE.get(today, 0),
        "dailyLimit": server.BRAVE_DAILY_LIMIT,
        **brave_last,
    }
    tavily["message"] = _provider_message(
        "Tavily",
        configured=tavily_configured,
        available=tavily_available,
        last_status=tavily_last.get("lastStatus"),
        last_results=tavily_last.get("lastResults"),
    )
    brave["message"] = _provider_message(
        "Brave",
        configured=brave_configured,
        available=brave_available,
        last_status=brave_last.get("lastStatus"),
        last_results=brave_last.get("lastResults"),
    )
    return {
        "ok": True,
        "providers": {
            "tavily": tavily,
            "brave": brave,
        },
        "summary": [tavily["message"], brave["message"]],
        "note": (
            "Diagnostica passiva: non consuma crediti. I dati si aggiornano "
            "quando AutoStorico usa realmente Brave o Tavily."
        ),
    }


def _diagnostic_tavily_market_search(
    query: str,
    payload: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    try:
        results = _ORIGINAL_TAVILY_MARKET_SEARCH(query, payload, diagnostics)
        elapsed = int((time.perf_counter() - started) * 1000)
        _record_provider_result(
            "tavily",
            status=200,
            result_count=len(results),
            operation="market_search",
            elapsed_ms=elapsed,
        )
        return results
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        status = int(getattr(exc, "code", 500) or 500)
        _record_provider_result(
            "tavily",
            status=status,
            result_count=0,
            operation="market_search",
            elapsed_ms=elapsed,
            error=str(exc),
        )
        raise


def _diagnostic_brave_market_search(
    query: str,
    payload: dict[str, Any],
    diagnostics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    try:
        results = _ORIGINAL_BRAVE_MARKET_SEARCH(query, payload, diagnostics)
        elapsed = int((time.perf_counter() - started) * 1000)
        _record_provider_result(
            "brave",
            status=200,
            result_count=len(results),
            operation="market_or_plate_search",
            elapsed_ms=elapsed,
        )
        return results
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        status = int(getattr(exc, "code", 500) or 500)
        _record_provider_result(
            "brave",
            status=status,
            result_count=0,
            operation="market_or_plate_search",
            elapsed_ms=elapsed,
            error=str(exc),
        )
        raise


def _diagnostic_search_defect_source_candidates(
    make: str,
    model: str,
    year: int | None = None,
    engine: str = "",
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = _ORIGINAL_SEARCH_DEFECT_SOURCE_CANDIDATES(make, model, year, engine)
        elapsed = int((time.perf_counter() - started) * 1000)
        candidates = result.get("candidates") if isinstance(result, dict) else []
        count = len(candidates) if isinstance(candidates, list) else int(result.get("count") or 0)
        _record_provider_result(
            "brave",
            status=200,
            result_count=count,
            operation="defect_research",
            elapsed_ms=elapsed,
        )
        return result
    except Exception as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        status = int(getattr(exc, "code", 500) or 500)
        _record_provider_result(
            "brave",
            status=status,
            result_count=0,
            operation="defect_research",
            elapsed_ms=elapsed,
            error=str(exc),
        )
        raise


def _diagnostic_do_get(self: server.AutoStoricoApi) -> None:
    request_path = server.urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
    if request_path == "/api/diagnostics/providers":
        self.send_json(provider_diagnostics_payload())
        return
    _ORIGINAL_DO_GET(self)


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
        if server.brave_search_available():
            try:
                brave = server.brave_market_search(query, payload, diagnostics)
                _merge_results(merged, brave, seen)
            except Exception as exc:
                diagnostics.setdefault("errors", []).append({"provider": "brave", "error": str(exc)[:160]})

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
        "brave": server.brave_search_available(),
        "tavily": False,
    }
    payload["note"] = (
        "I dati preliminari derivano da fonti pubbliche trovate con Brave Search. "
        "Le verifiche ufficiali restano separate e richiedono il CAPTCHA del portale quando previsto."
    )
    if diagnostics["errors"]:
        payload["diagnostics"] = diagnostics
    return 200, payload


server.tavily_market_search = _diagnostic_tavily_market_search
server.brave_market_search = _diagnostic_brave_market_search
server.search_defect_source_candidates = _diagnostic_search_defect_source_candidates
server.AutoStoricoApi.do_GET = _diagnostic_do_get
server.plate_info_lookup = enhanced_plate_info_lookup

if __name__ == "__main__":
    server.main()
