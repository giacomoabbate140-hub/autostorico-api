from __future__ import annotations

"""Runtime improvements for AutoStorico defect research.

Keeps Brave as the primary provider, calls Tavily only when Brave fails or does
not return enough trusted sources, shortens the live-research cache, and keeps
community candidates from generating user-facing update notifications.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import server_core as server

_ORIGINAL_DEFECT_RESEARCH_UPDATE_STATUS = server.defect_research_update_status

# A 30-day search cache prevented the scheduled collector from seeing new
# sources even when the workflow ran more often. Keep an explicit environment
# override when it is already shorter, otherwise cap it at 12 hours.
server.DEFECT_RESEARCH_CACHE_TTL_SECONDS = min(
    int(server.DEFECT_RESEARCH_CACHE_TTL_SECONDS),
    12 * 60 * 60,
)

# Extend manufacturer/authority coverage while keeping automatic alerts limited
# to official/manufacturer domains. Community sources are useful for review but
# never become push/update events automatically.
server.DEFECT_RESEARCH_SOURCES.update(
    {
        "kba.de": ("Kraftfahrt-Bundesamt", "official_candidate"),
        "honda.it": ("Honda Italia", "manufacturer_candidate"),
        "mazda.it": ("Mazda Italia", "manufacturer_candidate"),
        "opel.it": ("Opel Italia", "manufacturer_candidate"),
        "jeep-official.it": ("Jeep Italia", "manufacturer_candidate"),
        "suzuki.it": ("Suzuki Italia", "manufacturer_candidate"),
        "subaru.it": ("Subaru Italia", "manufacturer_candidate"),
        "jaguar.it": ("Jaguar Italia", "manufacturer_candidate"),
        "landrover.it": ("Land Rover Italia", "manufacturer_candidate"),
        "tesla.com": ("Tesla", "manufacturer_candidate"),
        "porsche.com": ("Porsche", "manufacturer_candidate"),
    }
)

_MIN_TRUSTED_BRAVE_RESULTS = 6
_NOTIFIABLE_SOURCE_TYPES = {"official_candidate", "manufacturer_candidate"}


def _trusted_result_count(items: list[tuple[str, dict[str, Any]]]) -> int:
    count = 0
    seen: set[str] = set()
    for _provider, item in items:
        url = server.safe_public_source_url(item.get("url"))
        if not url or url in seen or server.trusted_defect_source(url) is None:
            continue
        seen.add(url)
        count += 1
    return count


def _brave_items(query: str) -> list[tuple[str, dict[str, Any]]]:
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
            "User-Agent": "AutoStoricoDefectResearch/1.1",
            "X-Subscription-Token": server.BRAVE_SEARCH_API_KEY,
        },
    )
    data = server.read_provider_json(
        request,
        provider="brave",
        timeout=18,
        attempts=2,
    )
    if data.get("type") == "ErrorResponse":
        raise RuntimeError(str(data.get("message") or "Brave Search error"))
    return [
        ("brave", item)
        for item in (data.get("web", {}).get("results", []) or [])
        if isinstance(item, dict)
    ]


def _tavily_items(query: str) -> list[tuple[str, dict[str, Any]]]:
    api_key = server.normalize_provider_secret(server.TAVILY_API_KEY, "TAVILY_API_KEY")
    request_body = json.dumps(
        {
            "query": query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": 20,
            "country": "italy",
            "include_domains": list(server.DEFECT_RESEARCH_SOURCES.keys()),
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=request_body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "AutoStoricoDefectResearch/1.1",
        },
    )
    data = server.read_provider_json(
        request,
        provider="tavily",
        timeout=20,
        attempts=2,
    )
    if data.get("error"):
        raise RuntimeError(str(data.get("error")))
    return [
        ("tavily", item)
        for item in (data.get("results") or [])
        if isinstance(item, dict)
    ]


def improved_search_defect_source_candidates(
    make: str,
    model: str,
    year: int | None = None,
    engine: str = "",
) -> dict[str, Any]:
    if not server.defect_research_configured():
        raise RuntimeError("Ricerca fonti non configurata sul server.")

    clean_make = str(make or "").strip()
    clean_model = str(model or "").strip()
    if not clean_make or not clean_model:
        raise ValueError("Marca e modello sono obbligatori.")

    cache_key = server.defect_research_cache_key(clean_make, clean_model, year, engine)
    now = time.time()
    with server.DEFECT_RESEARCH_LOCK:
        cached = server.DEFECT_RESEARCH_CACHE.get(cache_key)
        if cached and now - cached[0] < server.DEFECT_RESEARCH_CACHE_TTL_SECONDS:
            return {**cached[1], "fromCache": True}

    context_terms = " ".join(
        term for term in [str(year or ""), str(engine or "").strip()] if term
    )
    query = (
        f'"{clean_make}" "{clean_model}" {context_terms} '
        "(richiamo OR recall OR campagna OR bollettino OR difetto OR problema "
        "OR affidabilita OR forum OR community OR proprietari)"
    )

    provider_items: list[tuple[str, dict[str, Any]]] = []
    providers_used: list[str] = []
    provider_errors: list[str] = []

    # Brave is the normal path. Tavily is deliberately not consumed when Brave
    # already produced enough trusted domains for a useful review batch.
    if server.brave_search_available():
        try:
            brave_items = _brave_items(query)
            provider_items.extend(brave_items)
            providers_used.append("brave")
        except (
            RuntimeError,
            OSError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            provider_errors.append(f"brave: {str(exc)[:160]}")

    trusted_from_brave = _trusted_result_count(provider_items)
    needs_fallback = trusted_from_brave < _MIN_TRUSTED_BRAVE_RESULTS
    if needs_fallback and server.tavily_market_search_available():
        try:
            provider_items.extend(_tavily_items(query))
            providers_used.append("tavily")
        except (
            RuntimeError,
            OSError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
        ) as exc:
            provider_errors.append(f"tavily: {str(exc)[:160]}")

    if not providers_used and provider_errors:
        raise RuntimeError("; ".join(provider_errors))

    candidates: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for provider, item in provider_items:
        url = server.safe_public_source_url(item.get("url"))
        trusted = server.trusted_defect_source(url)
        if not trusted or not url or url in seen_urls:
            continue
        source_name, source_type = trusted
        seen_urls.add(url)
        snippet = (
            item.get("content")
            if provider == "tavily"
            else " ".join(
                [
                    str(item.get("description") or ""),
                    *[str(value) for value in item.get("extra_snippets") or []],
                ]
            )
        )
        candidates.append(
            {
                "title": str(item.get("title") or "Fonte da verificare"),
                "url": url,
                "snippet": str(snippet or "").strip(),
                "sourceName": source_name,
                "sourceType": source_type,
                "researchCategory": (
                    "community"
                    if source_type == "community_candidate"
                    else "official_or_technical"
                ),
                "status": "pending_review",
            }
        )
        if len(candidates) >= 20:
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
        "providers": providers_used,
        "providerErrors": provider_errors,
        "fallbackUsed": "tavily" in providers_used,
        "trustedBraveCount": trusted_from_brave,
        "disclaimer": (
            "Candidati automatici: devono essere verificati e approvati prima "
            "di entrare nel catalogo visibile agli utenti."
        ),
    }
    with server.DEFECT_RESEARCH_LOCK:
        server.DEFECT_RESEARCH_CACHE[cache_key] = (now, result)
    return result


def official_only_defect_research_update_status() -> dict[str, Any]:
    """Keep fresh metadata, but notify only for official/manufacturer candidates."""
    base = _ORIGINAL_DEFECT_RESEARCH_UPDATE_STATUS()
    if not isinstance(base, dict):
        base = {}
    try:
        queue = json.loads(server.DEFECT_RESEARCH_QUEUE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        queue = {}
    if not isinstance(queue, dict):
        queue = {}

    candidates = queue.get("candidates") if isinstance(queue.get("candidates"), list) else []
    notifiable_pending = [
        item
        for item in candidates
        if isinstance(item, dict)
        and item.get("status") == "pending_review"
        and item.get("sourceType") in _NOTIFIABLE_SOURCE_TYPES
    ]

    # Preserve the original newest-batch logic (id, vehicles, details, sources)
    # so stale metadata is still replaced. Only pendingCount is filtered: the
    # Android app uses that field to decide whether a research notification is
    # emitted, so community-only batches remain silent.
    return {**base, "pendingCount": len(notifiable_pending)}


server.search_defect_source_candidates = improved_search_defect_source_candidates
server.defect_research_update_status = official_only_defect_research_update_status
