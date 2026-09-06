from __future__ import annotations

"""FCM push delivery for AutoStorico H24 expert consultations.

Firebase-specific credentials are preferred when configured. Otherwise the
existing Google Play service account is reused. This avoids creating a second
private key when the same Google Cloud project/service account already has FCM
permissions. Push delivery is always best-effort and never blocks a paid
consultation.
"""

import json
import os
import urllib.parse
from typing import Any

import server_core as server


_ORIGINAL_FINALIZE_CONSULTATION_DRAFT = server.finalize_consultation_draft
_ORIGINAL_CREATE_DEVELOPER_CONSULTATION = server.create_developer_consultation
_ORIGINAL_DO_GET = server.AutoStoricoApi.do_GET

_FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get(
    "AUTOSTORICO_FIREBASE_SERVICE_ACCOUNT_JSON", ""
).strip()
_FIREBASE_SERVICE_ACCOUNT_FILE = os.environ.get(
    "AUTOSTORICO_FIREBASE_SERVICE_ACCOUNT_FILE", "/etc/secrets/firebase-admin.json"
).strip()
_FIREBASE_PROJECT_ID = os.environ.get("AUTOSTORICO_FIREBASE_PROJECT_ID", "").strip()


def _dedicated_firebase_service_account_json() -> str:
    if _FIREBASE_SERVICE_ACCOUNT_JSON:
        return _FIREBASE_SERVICE_ACCOUNT_JSON
    if _FIREBASE_SERVICE_ACCOUNT_FILE:
        try:
            return server.Path(_FIREBASE_SERVICE_ACCOUNT_FILE).read_text(
                encoding="utf-8"
            ).strip()
        except OSError:
            pass
    return ""


def _firebase_service_account_json() -> tuple[str, str]:
    dedicated = _dedicated_firebase_service_account_json()
    if dedicated:
        return dedicated, "firebase"

    # AutoStorico already has a Google service account on Render for Play
    # subscriptions/Integrity. The same OAuth credential can call FCM when its
    # project/IAM permissions allow firebase.messaging.
    try:
        play = server.google_play_service_account_json()
    except Exception:
        play = ""
    if play:
        return play, "google_play"
    return "", "none"


def _firebase_config() -> tuple[dict[str, Any], str, str] | None:
    raw, source = _firebase_service_account_json()
    if not raw or server.service_account is None or server.AuthorizedSession is None:
        return None
    try:
        info = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(info, dict):
        return None
    project_id = _FIREBASE_PROJECT_ID or str(info.get("project_id") or "").strip()
    if not project_id:
        return None
    return info, project_id, source


def consultation_push_configured() -> bool:
    return bool(
        _firebase_config()
        and server.SUPABASE_URL
        and server.SUPABASE_SECRET_KEY
    )


def _developer_push_tokens() -> list[str]:
    profiles = server._supabase_json_request(
        "GET",
        "/rest/v1/profiles?role=eq.developer&select=id",
    )
    if not isinstance(profiles, list):
        return []
    developer_ids = [
        str(row.get("id") or "").strip()
        for row in profiles
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    ]
    if not developer_ids:
        return []

    tokens: list[str] = []
    for user_id in developer_ids:
        encoded = urllib.parse.quote(user_id, safe="")
        rows = server._supabase_json_request(
            "GET",
            "/rest/v1/push_devices"
            f"?user_id=eq.{encoded}&active=eq.true&select=token",
        )
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            token = str(row.get("token") or "").strip()
            if token and token not in tokens:
                tokens.append(token)
    return tokens


def _consultation_context(consultation_id: str) -> dict[str, str]:
    encoded = urllib.parse.quote(consultation_id, safe="")
    rows = server._supabase_json_request(
        "GET",
        "/rest/v1/consultations"
        f"?id=eq.{encoded}&select=id,client_id,vehicle_make,vehicle_model,subject,service_type",
    )
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return {}
    row = rows[0]
    return {
        "clientId": str(row.get("client_id") or "").strip(),
        "vehicleMake": str(row.get("vehicle_make") or "").strip(),
        "vehicleModel": str(row.get("vehicle_model") or "").strip(),
        "subject": str(row.get("subject") or "").strip(),
        "serviceType": str(row.get("service_type") or "h24").strip(),
    }


def _deactivate_push_token(token: str) -> None:
    try:
        encoded = urllib.parse.quote(token, safe="")
        server._supabase_json_request(
            "PATCH",
            f"/rest/v1/push_devices?token=eq.{encoded}",
            payload={"active": False},
            prefer="return=minimal",
        )
    except Exception:
        pass


def _authorized_fcm_session() -> tuple[Any, str] | None:
    config = _firebase_config()
    if config is None:
        return None
    info, project_id, _source = config
    credentials = server.service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/firebase.messaging"],
    )
    return server.AuthorizedSession(credentials), project_id


def _send_fcm(token: str, consultation_id: str, context: dict[str, str]) -> bool:
    session_config = _authorized_fcm_session()
    if session_config is None:
        return False
    session, project_id = session_config
    vehicle = " ".join(
        value
        for value in [context.get("vehicleMake", ""), context.get("vehicleModel", "")]
        if value
    ).strip()
    subject = str(context.get("subject") or "").strip()
    if vehicle and subject:
        body = f"{vehicle} · {subject}"
    elif vehicle:
        body = f"Nuova richiesta per {vehicle}"
    elif subject:
        body = subject
    else:
        body = "È arrivata una nuova richiesta all’Esperto online."

    endpoint = (
        "https://fcm.googleapis.com/v1/projects/"
        f"{urllib.parse.quote(project_id, safe='')}/messages:send"
    )
    response = session.post(
        endpoint,
        json={
            "message": {
                "token": token,
                "notification": {
                    "title": "Richiesto parere tecnico",
                    "body": body[:180],
                },
                "data": {
                    "type": "consultation_request",
                    "route": "expert_online",
                    "consultationId": consultation_id,
                },
                "android": {
                    "priority": "high",
                    "notification": {
                        "sound": "default",
                        "default_vibrate_timings": True,
                    },
                },
            }
        },
        timeout=12,
    )
    if response.status_code in {200, 201}:
        return True
    detail = response.text[:500].casefold()
    if response.status_code in {400, 404} and (
        "unregistered" in detail or "registration-token-not-registered" in detail
    ):
        _deactivate_push_token(token)
    return False


def _probe_fcm_authorization() -> dict[str, Any]:
    """Probe auth/API with a deliberately invalid token; sends no real push."""
    config = _firebase_config()
    if config is None:
        return {"attempted": False, "ready": False, "status": 0, "reason": "no_credentials"}
    try:
        session_config = _authorized_fcm_session()
        if session_config is None:
            return {"attempted": False, "ready": False, "status": 0, "reason": "no_session"}
        session, project_id = session_config
        endpoint = (
            "https://fcm.googleapis.com/v1/projects/"
            f"{urllib.parse.quote(project_id, safe='')}/messages:send"
        )
        response = session.post(
            endpoint,
            json={
                "message": {
                    "token": "autostorico-diagnostic-invalid-token",
                    "data": {"type": "diagnostic"},
                }
            },
            timeout=12,
        )
        # 400 means OAuth/project/API permission passed and FCM rejected only
        # the intentionally invalid registration token. 401/403 means auth/IAM
        # is not ready; 404 commonly means wrong project/API configuration.
        ready = response.status_code == 400
        detail = response.text[:300]
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                detail = str(error.get("status") or error.get("message") or detail)
        except Exception:
            pass
        return {
            "attempted": True,
            "ready": ready,
            "status": int(response.status_code),
            "reason": detail[:160],
        }
    except Exception as exc:
        return {
            "attempted": True,
            "ready": False,
            "status": 0,
            "reason": type(exc).__name__,
        }


def notify_developer_consultation(consultation_id: str) -> int:
    """Best-effort H24 push; never make a paid consultation fail because of FCM."""
    if not consultation_id or not consultation_push_configured():
        return 0
    try:
        context = _consultation_context(consultation_id)
        if context.get("serviceType", "h24") != "h24":
            return 0
        tokens = _developer_push_tokens()
    except Exception:
        return 0
    delivered = 0
    for token in tokens:
        try:
            if _send_fcm(token, consultation_id, context):
                delivered += 1
        except Exception:
            continue
    return delivered


def finalize_consultation_draft_with_push(
    draft_id: str,
    checkout_session_id: str,
    payment_intent_id: str,
) -> str:
    consultation_id = _ORIGINAL_FINALIZE_CONSULTATION_DRAFT(
        draft_id,
        checkout_session_id,
        payment_intent_id,
    )
    notify_developer_consultation(consultation_id)
    return consultation_id


def create_developer_consultation_with_push(
    user_id: str,
    fields: dict[str, str],
) -> str:
    consultation_id = _ORIGINAL_CREATE_DEVELOPER_CONSULTATION(user_id, fields)
    notify_developer_consultation(consultation_id)
    return consultation_id


def _push_diagnostic_do_get(self: server.AutoStoricoApi) -> None:
    parsed = server.urllib.parse.urlparse(self.path)
    request_path = parsed.path.rstrip("/") or "/"
    if request_path == "/api/diagnostics/push":
        try:
            active_devices = len(_developer_push_tokens())
        except Exception:
            active_devices = 0
        config = _firebase_config()
        project_id = config[1] if config is not None else ""
        source = config[2] if config is not None else "none"
        query = server.urllib.parse.parse_qs(parsed.query)
        probe = _probe_fcm_authorization() if query.get("probe") == ["1"] else None
        payload: dict[str, Any] = {
            "ok": True,
            "service": "expert_online_h24",
            "firebaseConfigured": config is not None,
            "pushConfigured": consultation_push_configured(),
            "credentialSource": source,
            "firebaseProjectId": project_id,
            "activeDeveloperDevices": active_devices,
        }
        if probe is not None:
            payload["fcmProbe"] = probe
        self.send_json(payload)
        return
    _ORIGINAL_DO_GET(self)


server.finalize_consultation_draft = finalize_consultation_draft_with_push
server.create_developer_consultation = create_developer_consultation_with_push
server.AutoStoricoApi.do_GET = _push_diagnostic_do_get
