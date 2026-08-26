from __future__ import annotations

import hashlib
from typing import Any

import patched_server
import server


_ORIGINAL_MARKET_CACHE_KEY = server.market_cache_key


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key) or []
    return str(values[0]).strip() if values else ""


def _missing_set(query: dict[str, list[str]]) -> set[str]:
    raw = _first(query, "missing")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _known_payload(query: dict[str, list[str]]) -> dict[str, str]:
    return {
        "vehicleType": _first(query, "knownVehicleType"),
        "make": _first(query, "knownBrand"),
        "model": _first(query, "knownModel"),
        "firstRegistration": _first(query, "knownRegistration"),
        "fuelType": _first(query, "knownFuelType"),
        "engineDisplacement": _first(query, "knownEngineDisplacement"),
        "powerKw": _first(query, "knownPowerKw"),
        "powerCv": _first(query, "knownPowerCv"),
    }


def _build_queries(plate: str, missing: set[str], known: dict[str, str]) -> list[str]:
    brand_model = " ".join(
        part for part in (known.get("make", ""), known.get("model", "")) if part
    ).strip()

    if not missing:
        return [
            f'"{plate}" marca modello',
            f'"{plate}" cilindrata kW',
            f'"{plate}" anno alimentazione',
        ]

    queries: list[str] = []
    if {"make", "model"} & missing:
        queries.append(f'"{plate}" marca modello auto')
    if "firstRegistration" in missing:
        suffix = f" {brand_model}" if brand_model else ""
        queries.append(f'"{plate}"{suffix} anno immatricolazione')
    if "fuelType" in missing:
        suffix = f" {brand_model}" if brand_model else ""
        queries.append(f'"{plate}"{suffix} alimentazione diesel benzina ibrida')
    if {"engineDisplacement", "powerKw", "powerCv"} & missing:
        suffix = f" {brand_model}" if brand_model else ""
        queries.append(f'"{plate}"{suffix} cilindrata kW CV')
    if "vehicleType" in missing:
        queries.append(f'"{plate}" tipo veicolo auto moto')

    # Keep API usage bounded: at most three focused queries per saved vehicle.
    deduped: list[str] = []
    for item in queries:
        if item not in deduped:
            deduped.append(item)
    return deduped[:3]


def _targeted_hints(
    plate: str,
    diagnostics: dict[str, Any],
    missing: set[str],
    known: dict[str, str],
) -> list[dict[str, Any]]:
    payload = {
        "brand": known.get("make", ""),
        "model": known.get("model", ""),
    }
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()

    for query in _build_queries(plate, missing, known):
        if server.brave_search_available():
            try:
                brave = server.brave_market_search(query, payload, diagnostics)
                patched_server._merge_results(merged, brave, seen)
            except Exception as exc:
                diagnostics.setdefault("errors", []).append(
                    {"provider": "brave", "error": str(exc)[:160]}
                )

        if len(merged) >= 8:
            break

    return merged[:8]


def diagnostic_market_cache_key(payload: dict[str, Any]) -> str:
    """Bypass the shared market cache only for the authorised developer build.

    Production requests keep the normal cache key. A private full-access build
    can send a fresh diagnosticNonce together with its authorised device hash;
    that request gets a one-off cache key and therefore performs a new market
    search without invalidating or changing cached results for real users.
    """
    base_key = _ORIGINAL_MARKET_CACHE_KEY(payload)
    nonce = str(payload.get("diagnosticNonce") or "").strip()
    developer_hash = str(payload.get("developerDeviceIdHash") or "").strip().lower()
    if not nonce or not server.developer_device_is_authorized(developer_hash):
        return base_key
    raw = f"{base_key}|developer-market-diagnostic|{nonce}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def optimized_plate_info_lookup(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    status, payload = patched_server._ORIGINAL_PLATE_INFO_LOOKUP(query)
    if status != 200 or not payload.get("ok"):
        return status, payload

    plate = str(payload.get("plate") or "")
    missing = _missing_set(query)
    known = _known_payload(query)
    saved_vehicle_request = any(known.values())

    # If the client says the saved vehicle has no missing fields, do not call
    # Brave or Tavily at all.
    if saved_vehicle_request and not missing:
        payload["vehicle"] = {**known, "provisional": False}
        payload["webHints"] = []
        payload["status"] = "complete_from_autostorico_archive"
        payload["configuredProviders"] = {
            "brave": server.brave_search_available(),
            "tavily": False,
        }
        payload["note"] = "Scheda già completa nell'archivio AutoStorico: nessuna chiamata esterna eseguita."
        return 200, payload

    base_hints = payload.get("webHints") if isinstance(payload.get("webHints"), list) else []
    hints = [item for item in base_hints if isinstance(item, dict)]
    diagnostics: dict[str, Any] = {"providers": [], "errors": []}

    if plate:
        extra = _targeted_hints(plate, diagnostics, missing, known)
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

    extracted = patched_server._extract_vehicle_from_hints(hints)

    # Return only fields that were missing for saved vehicles. Known fields stay
    # authoritative on the device and are not re-searched or overwritten.
    if saved_vehicle_request and missing:
        field_map = {
            "vehicleType": "vehicleType",
            "make": "make",
            "model": "model",
            "firstRegistration": "firstRegistration",
            "fuelType": "fuelType",
            "engineDisplacement": "engineDisplacement",
            "powerKw": "powerKw",
            "powerCv": "powerCv",
        }
        vehicle: dict[str, Any] = {"provisional": True}
        for request_key, result_key in field_map.items():
            if request_key in missing:
                vehicle[result_key] = extracted.get(result_key)
    else:
        vehicle = extracted

    useful = any(
        str(vehicle.get(key) or "").strip()
        for key in ("make", "model", "firstRegistration", "fuelType", "engineDisplacement", "powerKw", "powerCv")
    )

    payload["webHints"] = hints[:8]
    payload["vehicle"] = vehicle
    payload["status"] = "provisional_vehicle_data" if useful else payload.get("status", "no_public_match")
    payload["configuredProviders"] = {
        "brave": server.brave_search_available(),
        "tavily": False,
    }
    payload["requestedMissingFields"] = sorted(missing)
    payload["externalSearchCount"] = len(_build_queries(plate, missing, known)) if plate else 0
    payload["note"] = (
        "Per targhe già presenti AutoStorico ricerca solo i campi mancanti, "
        "limitando le query esterne. Le verifiche ufficiali restano separate."
    )
    if diagnostics["errors"]:
        payload["diagnostics"] = diagnostics
    return 200, payload


server.market_cache_key = diagnostic_market_cache_key
server.plate_info_lookup = optimized_plate_info_lookup

if __name__ == "__main__":
    server.main()
