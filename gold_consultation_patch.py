from __future__ import annotations

import json
import urllib.parse
from typing import Any


def install(server: Any) -> None:
    original_do_post = server.AutoStoricoApi.do_POST

    def create_gold_consultation(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        fields = server._consultation_payload(payload)
        user_id = str(user["id"])

        if not server.developer_user_is_authorized(user):
            entitlement = server.verify_defect_online_entitlement(
                {
                    "premiumPurchaseToken": str(payload.get("premiumPurchaseToken") or "").strip(),
                    "defectsGoldPurchaseToken": str(payload.get("defectsGoldPurchaseToken") or "").strip(),
                    "developerDeviceIdHash": str(payload.get("developerDeviceIdHash") or "").strip(),
                }
            )
            if not entitlement.get("ok"):
                message = str(entitlement.get("message") or "Difetti Gold non attivo.")
                error = PermissionError(message)
                setattr(error, "http_status", int(entitlement.get("status") or 402))
                raise error

        rows = server._supabase_json_request(
            "POST",
            "/rest/v1/consultations?select=id",
            payload={
                "client_id": user_id,
                "vehicle_make": fields["vehicle_make"],
                "vehicle_model": fields["vehicle_model"],
                "vehicle_engine": fields["vehicle_engine"],
                "subject": fields["subject"],
                "status": "open",
                "price_cents": 0,
                "currency": "EUR",
                "payment_status": "paid",
                "service_type": "gold",
            },
            prefer="return=representation",
        )
        if not isinstance(rows, list) or not rows or not rows[0].get("id"):
            raise RuntimeError("Consulenza Difetti Gold non creata")

        consultation_id = str(rows[0]["id"])
        try:
            server._supabase_json_request(
                "POST",
                "/rest/v1/consultation_messages",
                payload={
                    "consultation_id": consultation_id,
                    "sender_id": user_id,
                    "body": fields["body"],
                },
                prefer="return=minimal",
            )
        except Exception:
            encoded_id = urllib.parse.quote(consultation_id, safe="")
            try:
                server._supabase_json_request(
                    "DELETE",
                    f"/rest/v1/consultations?id=eq.{encoded_id}",
                    prefer="return=minimal",
                )
            except Exception:
                pass
            raise

        return {
            "ok": True,
            "goldIncluded": True,
            "consultationId": consultation_id,
        }

    def do_post(self: Any) -> None:
        request_path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        if request_path != "/api/consultations/gold":
            original_do_post(self)
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length > 0 else b"{}"
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("Richiesta non valida")

            auth = self.headers.get("Authorization", "")
            user = server.verify_supabase_user(auth)
            self.send_json(create_gold_consultation(user, payload))
        except json.JSONDecodeError:
            self.send_json({"error": "invalid_json", "message": "Richiesta non valida"}, status=400)
        except PermissionError as exc:
            self.send_json(
                {"error": "gold_required", "message": str(exc)},
                status=int(getattr(exc, "http_status", 402)),
            )
        except ValueError as exc:
            self.send_json({"error": "invalid_request", "message": str(exc)}, status=400)
        except RuntimeError as exc:
            self.send_json(
                {"error": "gold_consultation_unavailable", "message": str(exc)},
                status=503,
            )

    server.create_gold_consultation = create_gold_consultation
    server.AutoStoricoApi.do_POST = do_post
