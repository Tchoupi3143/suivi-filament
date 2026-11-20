#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Suivi Loyers — interface.
Petit serveur local (127.0.0.1 uniquement, protégé par un jeton aléatoire) qui sert
l'interface et pilote le moteur loyers.py. Bibliothèque standard Python uniquement.

    python3 serveur.py

Tant que l'interface est ouverte, le dossier ~/SuiviLoyers/a-importer/ est surveillé :
tout relevé qui y est déposé est importé dans la minute.
"""
import base64
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

RES = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RES)
import envoi                 # noqa: E402
import loyers as L           # noqa: E402
import planifier             # noqa: E402
import quittance as qt       # noqa: E402

PORT = int(os.environ.get("SUIVI_LOYERS_PORT", "47331"))
VERROU = threading.Lock()
JETON = secrets.token_urlsafe(24)
MOIS_AFFICHES = 12


# ----------------------------------------------------------------------------- état

def euros_vers_centimes(v, defaut=None):
    if v in (None, ""):
        if defaut is None:
            raise ValueError("Montant manquant")
        return defaut
    return L.releves.centimes(v)


def etat():
    d = L.charger()
    courant = L.mois(L.aujourdhui().isoformat())
    debut = L.mois_suivant(courant, -(MOIS_AFFICHES - 1))
    noms = {b["id"]: b["locataire"] for b in d["baux"]}
    baux = []
    for b in d["baux"]:
        sit, trop = L.situation(d, b)
        lignes = []
        for p, e in sorted(sit.items(), reverse=True):
            if p < debut or (p > courant and e["paye"] == 0):
                continue
            q = L.trouver_quittance(d, b["id"], p)
            r = L.trouver_quittance(d, b["id"], p, "recu")
            lignes.append({**e, "quittance": q, "recu": r, "relance": b.get("relances", {}).get(p)})
        loyer, charges = L.du(b, courant)
        baux.append({**b, "loyer": loyer, "charges": charges, "mois": lignes, "trop_percu": trop,
                     "mois_courant": sit.get(courant)})
    a_verifier = [o for o in d["operations"] if o["montant"] > 0 and not o.get("bail") and not o.get("ignoree")
                  and not o.get("manuel_libre")]
    recentes = [{**o, "locataire": noms.get(o.get("bail"))} for o in reversed(d["operations"][-300:])]
    du_mois = [x["mois_courant"] for x in baux if x.get("actif", True) and x["mois_courant"]]
    return {
        "bailleur": d["bailleur"], "reglages": d["reglages"],
        "smtp": {**d["smtp"], "mdp_defini": bool(envoi.mot_de_passe(L.DOSSIER))},
        "baux": baux, "a_verifier": [{**o, "suggestion_nom": noms.get(o.get("suggestion"))} for o in a_verifier],
        "operations": recentes, "journal": list(reversed(d["journal"][-60:])),
        "dernier_scan": d.get("dernier_scan"), "courant": courant,
        "stats": {"attendu": sum(e["du"] for e in du_mois), "recu": sum(min(e["paye"], e["du"]) for e in du_mois),
                  "en_retard": sum(1 for e in du_mois if "retard" in e["statut"]),
                  "a_verifier": len(a_verifier)},
        "dossiers": {"donnees": L.DATA, "boite": L.BOITE, "quittances": L.QUITTANCES},
        "banque": {**{k: v for k, v in d["banque"].items() if k not in ("state",)},
                   "cle_presente": os.path.exists(L.CLE_BANQUE), "connectee": L.banque_connectee(d)},
        "planification": planifier.etat(),
    }


# ----------------------------------------------------------------------------- actions

def bail_depuis(corps, b=None):
    nouveau = b is None
    b = b or {"id": None, "montants": [], "actif": True}
    locataire = (corps.get("locataire") or "").strip()
    if not locataire:
        raise ValueError("Indique le nom du locataire")
    debut = corps.get("debut") or L.mois(L.aujourdhui().isoformat())
    b.update(locataire=locataire, email=(corps.get("email") or "").strip(),
             logement=(corps.get("logement") or "").strip(),
             jour_echeance=max(1, min(31, int(corps.get("jour_echeance") or 5))),
             debut=debut[:7], fin=(corps.get("fin") or "")[:7] or None,
             motifs=[m.strip() for m in str(corps.get("motifs") or "").replace(",", "\n").splitlines() if m.strip()],
             envoi_auto=bool(corps.get("envoi_auto", True)), actif=bool(corps.get("actif", True)))
    loyer, charges = euros_vers_centimes(corps.get("loyer")), euros_vers_centimes(corps.get("charges"), 0)
    if nouveau or not b["montants"]:
        b["montants"] = [{"depuis": b["debut"], "loyer": loyer, "charges": charges}]
    else:
        depuis = (corps.get("revision_depuis") or "")[:7]
        actuel = L.du(b, depuis or L.mois(L.aujourdhui().isoformat()))
        if (loyer, charges) != actuel:
            if not depuis:
                raise ValueError("Indique à partir de quel mois le nouveau montant s'applique")
            b["montants"] = [m for m in b["montants"] if m["depuis"] != depuis]
            b["montants"].append({"depuis": depuis, "loyer": loyer, "charges": charges})
            b["montants"].sort(key=lambda m: m["depuis"])
        b["montants"][0]["depuis"] = min(b["montants"][0]["depuis"], b["debut"])
    return b


def action(chemin, corps):
    m = chemin.strip("/").split("/")[1:]
    with VERROU:
        if m == ["scan"]:
            return {"rapport": L.scanner()}
        d = L.charger()
        message = None
        if m == ["import"]:
            octets = base64.b64decode(corps.get("contenu") or "")
            n, deja = L.importer(d, octets, corps.get("nom") or "relevé")
            message = f"{n} nouvelle(s) opération(s) importée(s), {deja} déjà connue(s)"
        elif m == ["baux"]:
            b = bail_depuis(corps)
            b["id"] = d["prochain_bail"]
            d["prochain_bail"] += 1
            d["baux"].append(b)          # le rapprochement ci-dessous reconnaît aussi les virements déjà importés
        elif len(m) == 3 and m[0] == "baux":
            b = L.trouver_bail(d, int(m[1]))
            if m[2] == "modifier":
                bail_depuis(corps, b)
            elif m[2] == "supprimer":
                if any(o.get("bail") == b["id"] for o in d["operations"]):
                    raise ValueError("Ce bail a des paiements : décoche « Bail en cours » pour l'archiver.")
                d["baux"].remove(b)
                d["quittances"] = [q for q in d["quittances"] if q["bail"] != b["id"]]
            else:
                raise ValueError("Action inconnue")
        elif len(m) == 3 and m[0] == "operations":
            op = L.trouver_op(d, m[1])
            if m[2] == "affecter":
                L.affecter(d, op["id"], corps.get("bail"))
            elif m[2] == "ignorer":
                op["ignoree"] = True
                op.pop("bail", None)
            elif m[2] == "restaurer":
                op.pop("ignoree", None)
                op.pop("manuel_libre", None)
                op.pop("doublon_de", None)
            elif m[2] == "supprimer" and op.get("source") == "manuel":
                d["operations"].remove(op)
            else:
                raise ValueError("Action inconnue")
        elif m and m[0] == "banque":
            b = d["banque"]
            if m == ["banque", "config"]:
                b["app_id"] = (corps.get("app_id") or "").strip()
                b["redirect_url"] = (corps.get("redirect_url") or "").strip() or b["redirect_url"]
                if corps.get("cle"):
                    try:
                        L.enregistrer_cle_banque(corps["cle"])
                    except L.banque.ErreurBanque as ex:
                        raise ValueError(str(ex))
                message = "Réglages Enable Banking enregistrés"
            elif m == ["banque", "liste"]:
                try:
                    return {"banques": L.banque.banques(L.conf_banque(d), corps.get("pays") or "FR")}
                except L.banque.ErreurBanque as ex:
                    raise ValueError(str(ex))
            elif m == ["banque", "connecter"]:
                if not corps.get("banque"):
                    raise ValueError("Choisis ta banque dans la liste")
                try:
                    url, state = L.banque.demarrer(L.conf_banque(d), corps["banque"], b.get("pays") or "FR")
                except L.banque.ErreurBanque as ex:
                    raise ValueError(str(ex))
                b.update(banque=corps["banque"], state=state)
                L.sauver(d)
                return {"url": url}
            elif m == ["banque", "terminer"]:
                try:
                    code = L.banque.code_depuis(corps.get("adresse"), b.get("state"))
                    r = L.banque.terminer(L.conf_banque(d), code)
                except (L.banque.ErreurBanque, KeyError) as ex:
                    raise ValueError(str(ex))
                b.update(session_id=r["session_id"], comptes=r["comptes"], valide_jusqu=r["valide_jusqu"],
                         alerte_expiration="", state="")
                b.pop("erreur", None)
                if b.get("compte") not in [c["uid"] for c in r["comptes"]]:
                    b["compte"] = r["comptes"][0]["uid"] if len(r["comptes"]) == 1 else ""
                message = "Banque connectée" + ("" if b["compte"] else " : choisis le compte qui reçoit les loyers")
            elif m == ["banque", "compte"]:
                if corps.get("uid") not in [c["uid"] for c in b.get("comptes", [])]:
                    raise ValueError("Compte inconnu")
                b["compte"] = corps["uid"]
                b["derniere_synchro"] = ""
            elif m == ["banque", "deconnecter"]:
                b.update(session_id="", comptes=[], compte="", valide_jusqu="", derniere_synchro="")
                message = "Banque déconnectée"
            else:
                raise ValueError("Requête inconnue")
            L.sauver(d)
            if b.get("compte") and L.banque_connectee(d) and m in (["banque", "terminer"], ["banque", "compte"]):
                rapport = L.scanner(boite=False)          # première synchronisation tout de suite
                return {"message": f"{message or 'Compte choisi'} — {rapport['banque']}", "rapport": rapport}
            return {"message": message}
        elif m == ["planification"]:
            try:
                return {"message": planifier.retirer() if corps.get("retirer") else
                        planifier.installer(corps.get("heure") or "09:00")}
            except Exception as ex:
                raise ValueError(f"Planification impossible : {ex}")
        elif m == ["paiement"]:
            L.ajouter_paiement_manuel(d, corps.get("bail"), corps.get("date"),
                                      euros_vers_centimes(corps.get("montant")), corps.get("note") or "")
        elif m in (["quittance", "envoyer"], ["recu"], ["relance"]):
            b = L.trouver_bail(d, int(corps.get("bail")))
            periode = corps.get("periode")
            if m == ["relance"]:
                try:
                    L.relancer(d, b, periode)
                except Exception as ex:
                    raise ValueError(f"Relance impossible : {ex}")
                message = f"Relance envoyée à {b['email']}"
            else:
                e = L.situation(d, b)[0][periode]
                type_ = "quittance" if m[0] == "quittance" else "recu"
                if type_ == "quittance" and e["paye"] < e["du"]:
                    raise ValueError("Ce mois n'est pas entièrement payé : envoie plutôt un reçu.")
                if type_ == "recu" and not e["paye"]:
                    raise ValueError("Aucun paiement reçu pour ce mois.")
                q = L.trouver_quittance(d, b["id"], periode, type_)
                if not q or q["montant"] != (e["du"] if type_ == "quittance" else e["paye"]):
                    q = L.fabriquer(d, b, e, type_)
                try:
                    L.envoyer_quittance(d, q)
                except Exception as ex:
                    q["erreur"] = str(ex)[:300]
                    L.sauver(d)
                    raise ValueError(f"Envoi impossible : {ex}")
                message = f"{'Quittance' if type_ == 'quittance' else 'Reçu'} envoyé(e) à {b['email']}"
        elif m == ["reglages"]:
            for cle in ("bailleur", "smtp", "reglages"):
                if isinstance(corps.get(cle), dict):
                    for k, v in corps[cle].items():
                        if k in d[cle] or k in ("signataire", "nom_expediteur"):
                            d[cle][k] = v
            d["smtp"]["port"] = int(d["smtp"].get("port") or 465)
            d["reglages"]["jours_grace"] = int(d["reglages"].get("jours_grace") or 0)
            for cle in ("sujet", "texte"):
                try:
                    d["reglages"][cle].format(**{k: "" for k in ("locataire", "periode", "montant", "date_paiement",
                                                                 "logement", "bailleur")})
                except (KeyError, ValueError, IndexError) as ex:
                    raise ValueError(f"Modèle d'e-mail invalide ({cle}) : {ex}")
            if corps.get("mdp"):
                os.makedirs(L.DOSSIER, exist_ok=True)
                envoi.enregistrer_mot_de_passe(L.DOSSIER, corps["mdp"])
        elif m == ["test-email"]:
            a = d["bailleur"].get("email")
            if not a:
                raise ValueError("Renseigne d'abord ton adresse e-mail (Réglages > Bailleur)")
            try:
                envoi.envoyer(d["smtp"], L.DOSSIER, a, "Suivi Loyers — e-mail de test",
                              "L'envoi des quittances fonctionne.\n")
            except Exception as ex:
                raise ValueError(f"Échec : {ex}")
            return {"message": f"E-mail de test envoyé à {a}"}
        else:
            raise ValueError("Requête inconnue")
        L.rapprocher(d)
        cr = L.emettre(d)
        d["dernier_scan"] = L.maintenant()
        L.sauver(d)
        if cr["envoyees"]:
            message = (message + " — " if message else "") + f"{len(cr['envoyees'])} quittance(s) envoyée(s)"
        if cr["erreurs"]:
            message = (message + " — " if message else "") + f"échec d'envoi : {cr['erreurs'][0]}"
        return {"message": message}


# ----------------------------------------------------------------------------- HTTP

class Gestion(BaseHTTPRequestHandler):
    server_version = "SuiviLoyers"

    def log_message(self, *a):
        pass

    def _envoyer(self, code, data, type_="application/json; charset=utf-8", extra=None):
        corps = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corps)

    def _autorise(self):
        q = parse_qs(urlparse(self.path).query)
        return secrets.compare_digest(self.headers.get("X-Jeton") or (q.get("t") or [""])[0], JETON)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            if not self._autorise():
                return self._envoyer(403, "Lance Suivi Loyers (python3 serveur.py) pour ouvrir l'interface.".encode(),
                                     "text/plain; charset=utf-8")
            html = open(os.path.join(RES, "index.html"), "rb").read().replace(b"@JETON@", JETON.encode())
            return self._envoyer(200, html, "text/html; charset=utf-8")
        if not self._autorise():
            return self._envoyer(403, {"erreur": "interdit"})
        if u.path == "/api/etat":
            with VERROU:
                return self._envoyer(200, etat())
        if u.path == "/api/pdf":
            q = parse_qs(u.query)
            d = L.charger()
            fiche = L.trouver_quittance(d, int(q["bail"][0]), q["periode"][0], q.get("type", ["quittance"])[0])
            if not fiche or not os.path.exists(L.chemin_pdf(fiche)):
                return self._envoyer(404, {"erreur": "Document introuvable"})
            with open(L.chemin_pdf(fiche), "rb") as f:
                return self._envoyer(200, f.read(), "application/pdf",
                                     {"Content-Disposition": f'inline; filename="{os.path.basename(fiche["fichier"])}"'})
        self._envoyer(404, {"erreur": "introuvable"})

    def do_POST(self):
        if not self._autorise():
            return self._envoyer(403, {"erreur": "interdit"})
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20 * 1024 * 1024:
            return self._envoyer(413, {"erreur": "Fichier trop volumineux"})
        try:
            corps = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            corps = {}
        p = urlparse(self.path).path
        if p == "/api/quitter":
            self._envoyer(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        try:
            r = action(p, corps)
            with VERROU:
                self._envoyer(200, {**etat(), **(r or {})})
        except (ValueError, KeyError, TypeError) as e:
            self._envoyer(400, {"erreur": str(e) or "Requête invalide"})
        except Exception as e:             # SMTP, réseau, fichier… : message lisible plutôt qu'une coupure
            self._envoyer(400, {"erreur": f"{type(e).__name__} : {e}"})


def surveiller_boite():
    """Importe automatiquement les relevés déposés dans a-importer/ tant que l'interface tourne."""
    while True:
        time.sleep(60)
        try:
            if os.path.isdir(L.BOITE) and any(not f.startswith(".") for f in os.listdir(L.BOITE)):
                with VERROU:
                    L.scanner()
        except Exception:
            pass


if __name__ == "__main__":
    os.makedirs(L.BOITE, exist_ok=True)
    if planifier.etat():
        try:
            planifier.copier_moteur()           # nouvelle version du programme -> tâche quotidienne à jour
        except OSError:
            pass
    try:
        serveur = ThreadingHTTPServer(("127.0.0.1", PORT), Gestion)
    except OSError:
        serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
    url = f"http://127.0.0.1:{serveur.server_address[1]}/?t={JETON}"
    threading.Thread(target=surveiller_boite, daemon=True).start()
    print(f"Suivi Loyers : {url}\n(Ctrl+C pour arrêter)", flush=True)
    if not os.environ.get("SUIVI_LOYERS_SANS_NAVIGATEUR"):
        webbrowser.open(url)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
