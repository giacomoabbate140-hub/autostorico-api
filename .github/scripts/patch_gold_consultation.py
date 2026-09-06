from pathlib import Path

p = Path('server_core.py')
s = p.read_text(encoding='utf-8')

# 1) Add secure server-side creator for Difetti Gold consultations.
anchor = "\ndef create_consultation_checkout(\n    user: dict[str, Any], payload: dict[str, Any]\n) -> dict[str, Any]:\n"
if 'def create_gold_consultation(' not in s:
    if anchor not in s:
        raise SystemExit('create_consultation_checkout anchor not found')
    fn = r'''
def create_gold_consultation(
    user: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Open a consultation included in a verified Difetti Gold entitlement."""
    fields = _consultation_payload(payload)
    user_id = str(user["id"])

    if not developer_user_is_authorized(user):
        entitlement = verify_defect_online_entitlement(
            {
                "premiumPurchaseToken": str(
                    payload.get("premiumPurchaseToken") or ""
                ).strip(),
                "defectsGoldPurchaseToken": str(
                    payload.get("defectsGoldPurchaseToken") or ""
                ).strip(),
                "developerDeviceIdHash": str(
                    payload.get("developerDeviceIdHash") or ""
                ).strip(),
            }
        )
        if not entitlement.get("ok"):
            message = str(
                entitlement.get("message")
                or "Difetti Gold non attivo."
            )
            error = PermissionError(message)
            setattr(error, "http_status", int(entitlement.get("status") or 402))
            raise error

    rows = _supabase_json_request(
        "POST",
        "/rest/v1/consultations?select=id",
        payload={
            "client_id": user_id,
            "vehicle_make": fields["vehicle_make"],
            "vehicle_model": fields["vehicle_model"],
            "vehicle_engine": fields["vehicle_engine"],
            "subject": fields["subject"],
            "status": "open",
            "price_cents": CONSULTATION_PRICE_CENTS,
            "currency": "EUR",
            "payment_status": "paid",
            "service_type": "gold",
        },
        prefer="return=representation",
    )
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Consulenza Difetti Gold non creata")
    consultation_id = str(rows[0].get("id") or "").strip()
    if not consultation_id:
        raise RuntimeError("Consulenza Difetti Gold non creata")

    try:
        _supabase_json_request(
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
            _supabase_json_request(
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

'''
    s = s.replace(anchor, '\n' + fn + anchor.lstrip('\n'), 1)

# 2) Whitelist/authenticate the Gold endpoint in the same group as checkout.
needle = '            "/api/consultations/checkout",\n            "/api/consultations/delete",'
replacement = '            "/api/consultations/checkout",\n            "/api/consultations/gold",\n            "/api/consultations/delete",'
if '"/api/consultations/gold"' not in s:
    if s.count(needle) < 2:
        raise SystemExit('consultation route sets not found')
    s = s.replace(needle, replacement)

# 3) Dispatch Gold before Stripe checkout.
checkout_branch = '            if request_path == "/api/consultations/checkout":\n'
if 'if request_path == "/api/consultations/gold":' not in s:
    if checkout_branch not in s:
        raise SystemExit('checkout dispatch not found')
    gold_branch = r'''            if request_path == "/api/consultations/gold":
                try:
                    user = verify_supabase_user(auth)
                    self.send_json(create_gold_consultation(user, payload))
                except PermissionError as exc:
                    self.send_json(
                        {"error": "gold_required", "message": str(exc)},
                        status=int(getattr(exc, "http_status", 402)),
                    )
                except (ValueError, RuntimeError) as exc:
                    self.send_json(
                        {"error": "gold_consultation_unavailable", "message": str(exc)},
                        status=503 if isinstance(exc, RuntimeError) else 400,
                    )
                return
'''
    s = s.replace(checkout_branch, gold_branch + checkout_branch, 1)

# 4) Advertise endpoint in startup log.
log_line = '    print("Endpoint: POST /api/consultations/checkout")\n'
if 'Endpoint: POST /api/consultations/gold' not in s:
    if log_line not in s:
        raise SystemExit('startup log anchor not found')
    s = s.replace(
        log_line,
        log_line + '    print("Endpoint: POST /api/consultations/gold")\n',
        1,
    )

p.write_text(s, encoding='utf-8')
