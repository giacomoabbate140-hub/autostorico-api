from pathlib import Path

path = Path('server.py')
text = path.read_text(encoding='utf-8')

handler_anchor = '\n\nclass AutoStoricoApi(BaseHTTPRequestHandler):\n'
if handler_anchor not in text:
    raise SystemExit('handler anchor not found')

helper = '''\n\ndef normalize_plate_info_plate(value: Any) -> str:\n    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())\n\n\ndef plate_info_format(plate: str) -> str:\n    if re.fullmatch(r"[A-HJ-NPR-TV-Z]{2}[0-9]{3}[A-HJ-NPR-TV-Z]{2}", plate):\n        return "modern"\n    if re.fullmatch(r"[A-Z]{2}[0-9]{5,6}", plate):\n        return "provincial_old"\n    return "unknown"\n\n\ndef plate_info_lookup(query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:\n    plate = normalize_plate_info_plate((query.get("plate") or [""])[0])\n    plate_format = plate_info_format(plate)\n    if not plate or plate_format == "unknown":\n        return 400, {\n            "ok": False,\n            "error": "invalid_plate",\n            "message": "Formato targa non riconosciuto.",\n        }\n\n    diagnostics: dict[str, Any] = {"providers": [], "errors": []}\n    lookup_payload: dict[str, Any] = {"brand": "", "model": ""}\n    listings: list[dict[str, Any]] = []\n    query_text = f'"{plate}" targa auto usata'\n\n    if BRAVE_SEARCH_API_KEY:\n        try:\n            listings = brave_market_search(query_text, lookup_payload, diagnostics)\n        except Exception as exc:\n            diagnostics["errors"].append({"provider": "brave", "error": str(exc)[:160]})\n\n    if not listings and SERPAPI_API_KEY:\n        try:\n            listings = serpapi_market_search(query_text, lookup_payload, diagnostics)\n        except Exception as exc:\n            diagnostics["errors"].append({"provider": "serpapi", "error": str(exc)[:160]})\n\n    safe_listings = [\n        {\n            "source": str(item.get("source") or "Fonte web"),\n            "title": str(item.get("title") or "")[:160],\n            "url": str(item.get("url") or ""),\n            "year": item.get("year"),\n            "km": item.get("km"),\n        }\n        for item in listings[:5]\n    ]\n\n    return 200, {\n        "ok": True,\n        "plate": plate,\n        "plateFormat": plate_format,\n        "status": "public_listing_hints" if safe_listings else "no_public_match",\n        "vehicle": {\n            "vehicleType": "",\n            "make": "",\n            "model": "",\n            "firstRegistration": "",\n            "fuelType": "",\n            "powerKw": None,\n            "powerCv": None,\n            "provisional": True,\n        },\n        "webHints": safe_listings,\n        "configuredProviders": {\n            "brave": bool(BRAVE_SEARCH_API_KEY),\n            "serpapi": bool(SERPAPI_API_KEY),\n        },\n        "officialData": {\n            "revision": None,\n            "insurance": None,\n            "euroClass": None,\n            "newDriverEligible": None,\n        },\n        "note": "Le ricerche web sono solo indizi pubblici. I dati ufficiali saranno mostrati solo quando verificati da una fonte ufficiale o autorizzata.",\n    }\n'''

if 'def plate_info_lookup(' not in text:
    text = text.replace(handler_anchor, helper + handler_anchor, 1)

route_anchor = '''        if request_path in {"/api/defects", "/defects"}:\n            self.send_json(lookup_defects(urllib.parse.parse_qs(parsed_url.query)))\n            return\n'''
route = '''        if request_path == "/api/plate-info":\n            status_code, payload = plate_info_lookup(urllib.parse.parse_qs(parsed_url.query))\n            self.send_json(payload, status=status_code)\n            return\n'''

if '/api/plate-info' not in text:
    if route_anchor not in text:
        raise SystemExit('route anchor not found')
    text = text.replace(route_anchor, route_anchor + route, 1)

path.write_text(text, encoding='utf-8')
