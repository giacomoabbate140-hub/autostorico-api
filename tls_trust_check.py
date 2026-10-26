"""Temporary startup audit of the deployed HTTP clients; no credentials are sent."""

from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import version
import json
import os
import ssl
import threading
import urllib.error
import urllib.request

import requests


PROBES = {
    "control": "https://render.com/",
    "emudhra": "https://dv-g3b-emudhra.we-have-a-problem.com/",
    "emudhra_cross_signed": "https://dv-g3b-aaa-emudhra.we-have-a-problem.com/",
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _certificate_error(error):
    pending = [error]
    seen = set()
    while pending:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return current
        pending.extend(getattr(current, "args", ()))
        pending.extend((getattr(current, "reason", None), current.__cause__, current.__context__))
    return None


def probe(client, name):
    result = {"client": client, "probe": name}
    try:
        if client == "requests":
            with requests.Session() as session:
                with session.get(PROBES[name], timeout=(8, 8), allow_redirects=False, stream=True) as response:
                    result.update(outcome="accepted", status=response.status_code)
        else:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(PROBES[name], timeout=8) as response:
                result.update(outcome="accepted", status=response.status)
    except urllib.error.HTTPError as error:
        # An HTTP response, including a redirect or a 5xx, proves TLS was accepted.
        result.update(outcome="accepted", status=error.code)
        error.close()
    except Exception as error:
        certificate_error = _certificate_error(error)
        if certificate_error is None:
            result.update(outcome="inconclusive", errorType=type(error).__name__)
        else:
            code = getattr(certificate_error, "verify_code", None)
            # Expiry, not-yet-valid, and hostname mismatch do not prove CA distrust.
            outcome = "inconclusive" if code in (None, 9, 10, 62, 64) else "rejected"
            result.update(outcome=outcome, verifyCode=code)
    return result


def summarize(checks):
    keyed = {(item["client"], item["probe"]): item["outcome"] for item in checks}
    if any(keyed.get((client, name)) == "accepted" for client in ("requests", "urllib") for name in PROBES if name != "control"):
        return "fail"
    if all(keyed.get((client, name)) == ("accepted" if name == "control" else "rejected") for client in ("requests", "urllib") for name in PROBES):
        return "pass"
    return "inconclusive"


def run():
    try:
        jobs = [(client, name) for client in ("requests", "urllib") for name in PROBES]
        with ThreadPoolExecutor(max_workers=4) as pool:
            checks = list(pool.map(lambda job: probe(*job), jobs))
        report = {
            "result": summarize(checks),
            "deployment": os.environ.get("RENDER_GIT_COMMIT", "unknown"),
            "certifiVersion": version("certifi"),
            "checks": checks,
        }
        print("AUTOSTORICO_TLS_VERIFY " + json.dumps(report, sort_keys=True), flush=True)
    except Exception as error:
        print("AUTOSTORICO_TLS_VERIFY " + json.dumps({"result": "inconclusive", "errorType": type(error).__name__}), flush=True)


def start():
    # The diagnostic never blocks readiness or receives application credentials.
    threading.Thread(target=run, name="tls-trust-check", daemon=True).start()


if __name__ == "__main__":
    run()
