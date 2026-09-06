from __future__ import annotations

"""FCM push delivery for AutoStorico H24 expert consultations.

Firebase-specific credentials are preferred when configured. Otherwise the
existing Google Play service account is reused. This avoids creating a second
private key when the same Google Cloud project/service account already has FCM
permissions. Push delivery is always best-effort and never blocks a paid
consultation.
"""

import base64
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


def _authorized_google_session(scopes: list[str]) -> tuple[Any, str] | None:
    config = _firebase_config()
    if config is None:
        return None
    info, project_id, _source = config
    credentials = server.service_account.Credentials.from_service_account_info(
        info,
        scopes=scopes,
    )
    return server.AuthorizedSession(credentials), project_id


def _authorized_fcm_session() -> tuple[Any, str] | None:
    return _authorized_google_session(
        ["https://www.googleapis.com/auth/firebase.messaging"]
    )


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


def _probe_firebase_management() -> dict[str, Any]:
    """Read Firebase project/app metadata using existing Google credentials."""
    try:
        session_config = _authorized_google_session(
            ["https://www.googleapis.com/auth/cloud-platform"]
        )
        if session_config is None:
            return {"attempted": False, "status": 0, "reason": "no_session", "apps": []}
        session, project_id = session_config
        project_url = (
            "https://firebase.googleapis.com/v1beta1/projects/"
            f"{urllib.parse.quote(project_id, safe='')}"
        )
        project_response = session.get(project_url, timeout=12)
        if project_response.status_code != 200:
            detail = project_response.text[:300]
            try:
                payload = project_response.json()
                error = payload.get("error") if isinstance(payload, dict) else None
                if isinstance(error, dict):
                    detail = str(error.get("status") or error.get("message") or detail)
            except Exception:
                pass
            return {
                "attempted": True,
                "status": int(project_response.status_code),
                "reason": detail[:160],
                "apps": [],
            }

        apps_url = project_url + "/androidApps?pageSize=100"
        apps_response = session.get(apps_url, timeout=12)
        if apps_response.status_code != 200:
            return {
                "attempted": True,
                "status": int(apps_response.status_code),
                "reason": "android_apps_unavailable",
                "apps": [],
            }
        apps_payload = apps_response.json()
        apps = apps_payload.get("apps") if isinstance(apps_payload, dict) else []
        public_apps: list[dict[str, Any]] = []
        for app in apps if isinstance(apps, list) else []:
            if not isinstance(app, dict):
                continue
            name = str(app.get("name") or "").strip()
            public_app: dict[str, Any] = {
                "name": name,
                "appId": str(app.get("appId") or "").strip(),
                "packageName": str(app.get("packageName") or "").strip(),
                "displayName": str(app.get("displayName") or "").strip(),
            }
            if name:
                config_response = session.get(
                    f"https://firebase.googleapis.com/v1beta1/{name}/config",
                    timeout=12,
                )
                if config_response.status_code == 200:
                    config_payload = config_response.json()
                    encoded = (
                        str(config_payload.get("configFileContents") or "")
                        if isinstance(config_payload, dict)
                        else ""
                    )
                    if encoded:
                        try:
                            decoded = base64.b64decode(encoded).decode("utf-8")
                            google_config = json.loads(decoded)
                            project_info = google_config.get("project_info") or {}
                            clients = google_config.get("client") or []
                            public_app["projectNumber"] = str(
                                project_info.get("project_number") or ""
                            )
                            public_app["projectId"] = str(
                                project_info.get("project_id") or project_id
                            )
                            for client in clients if isinstance(clients, list) else []:
                                if not isinstance(client, dict):
                                    continue
                                client_info = client.get("client_info") or {}
                                android_info = client_info.get("android_client_info") or {}
                                if str(android_info.get("package_name") or "") != public_app["packageName"]:
                                    continue
                                public_app["mobilesdkAppId"] = str(
                                    client_info.get("mobilesdk_app_id") or public_app["appId"]
                                )
                                api_keys = client.get("api_key") or []
                                if isinstance(api_keys, list) and api_keys:
                                    first_key = api_keys[0] if isinstance(api_keys[0], dict) else {}
                                    public_app["apiKey"] = str(
                                        first_key.get("current_key") or ""
                                    )
                                break
                        except Exception:
                            public_app["configParse"] = "failed"
            public_apps.append(public_app)
        return {
            "attempted": True,
            "status": 200,
            "reason": "ok",
            "apps": public_apps,
        }
    except Exception as exc:
        return {
            "attempted": True,
            "status": 0,
            "reason": type(exc).__name__,
            "apps": [],
        }


def notify_developer_consultation(consultation_id: str) -> int:
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
        management = (
            _probe_firebase_management() if query.get("manage") == ["1"] else None
        )
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
        if management is not None:
            payload["firebaseManagement"] = management
        self.send_json(payload)
        return
    _ORIGINAL_DO_GET(self)


server.finalize_consultation_draft = finalize_consultation_draft_with_push
server.create_developer_consultation = create_developer_consultation_with_push
server.AutoStoricoApi.do_GET = _push_diagnostic_do_get
