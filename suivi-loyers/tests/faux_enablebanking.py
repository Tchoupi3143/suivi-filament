# SPDX-License-Identifier: GPL-3.0-or-later
"""Faux serveur Enable Banking pour les tests : vérifie la signature du JWT et sert des opérations."""
import base64
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class FauxEnableBanking:
    def __init__(self, n, e, app_id, transactions):
        self.appels, self.transactions = [], transactions
        parent = self

        class Gestion(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def repondre(self, code, data):
                corps = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def verifier(self):
                jeton = (self.headers.get("Authorization") or "")[7:]
                h, p, sig = jeton.split(".")
                entete, charge = json.loads(_b64(h)), json.loads(_b64(p))
                em = pow(int.from_bytes(_b64(sig), "big"), e, n).to_bytes((n.bit_length() + 7) // 8, "big")
                ok = (em.endswith(hashlib.sha256(f"{h}.{p}".encode()).digest()) and entete["kid"] == app_id
                      and entete["alg"] == "RS256" and charge["aud"] == "api.enablebanking.com")
                if not ok:
                    self.repondre(401, {"message": "Invalid JWT", "error": "UNAUTHORIZED"})
                return ok

            def do_GET(self):
                if not self.verifier():
                    return
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                parent.appels.append(("GET", u.path, q))
                if u.path == "/aspsps":
                    return self.repondre(200, {"aspsps": [
                        {"name": "Banque Populaire Grand Ouest", "country": "FR", "maximum_consent_validity": 15552000},
                        {"name": "BRED", "country": "FR", "maximum_consent_validity": 7776000}]})
                if u.path == "/accounts/compte-loyers/transactions":
                    t = [x for x in parent.transactions if x["booking_date"] >= q["date_from"]]
                    if "continuation_key" not in q:
                        return self.repondre(200, {"transactions": t[:2], "continuation_key": "suite" if len(t) > 2 else None})
                    return self.repondre(200, {"transactions": t[2:], "continuation_key": None})
                self.repondre(404, {"message": "Not found"})

            def do_POST(self):
                if not self.verifier():
                    return
                corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                parent.appels.append(("POST", self.path, corps))
                if self.path == "/auth":
                    return self.repondre(200, {"url": "https://banque.example/auth?x=1", "authorization_id": "a1"})
                if self.path == "/sessions":
                    if corps.get("code") != "CODE-OK":
                        return self.repondre(422, {"message": "Wrong authorization code", "error": "WRONG_AUTH_CODE"})
                    return self.repondre(200, {"session_id": "sess-1", "access": {"valid_until": "2027-05-15T10:00:00+00:00"},
                                               "accounts": [{"uid": "compte-loyers", "name": "Compte loyers",
                                                             "account_id": {"iban": "FR7610000000000000000000000"}}]})
                self.repondre(404, {"message": "Not found"})

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def arreter(self):
        self.serveur.shutdown()
        self.serveur.server_close()
