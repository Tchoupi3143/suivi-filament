#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tchoupi3143 — Suivi Filament
"""
Suivi Filament — application Mac.
Petit serveur local (127.0.0.1 uniquement) qui sert l'interface et lit/écrit
~/SuiviFilament/bobines.json, le même fichier que le script de post-traitement
d'ElegooSlicer. Bibliothèque standard Python uniquement.
"""
import datetime as dt
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

RES = os.path.dirname(os.path.abspath(__file__))
DOSSIER = os.path.expanduser(os.environ.get("SUIVI_FILAMENT_DOSSIER", "~/SuiviFilament"))
os.makedirs(DOSSIER, exist_ok=True)
os.environ["SUIVI_FILAMENT_DATA"] = os.path.join(DOSSIER, "bobines.json")
sys.path.insert(0, RES)
import suivi_filament as sf          # noqa: E402  (moteur partagé avec le slicer)
import configurer_slicer as cs       # noqa: E402
import catalogue_elegoo as ce        # noqa: E402

CATALOGUE = os.path.join(DOSSIER, "catalogue_elegoo.json")        # dernière version téléchargée
CATALOGUE_BASE = os.path.join(RES, "catalogue_elegoo_base.json")   # version livrée avec l'app


def lire_catalogue():
    for f in (CATALOGUE, CATALOGUE_BASE):
        try:
            with open(f, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            continue
    return {"gammes": [], "maj": None}


def actualiser_catalogue():
    cat = ce.telecharger()
    tmp = CATALOGUE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cat, fh, ensure_ascii=False)
    os.replace(tmp, CATALOGUE)
    return cat


def actualiser_si_ancien():
    """Au démarrage, en arrière-plan : prix de plus de 7 jours -> mise à jour silencieuse."""
    try:
        maj = lire_catalogue().get("maj")
        if not maj or (dt.date.today() - dt.date.fromisoformat(maj)).days >= 7:
            actualiser_catalogue()
    except Exception:
        pass   # hors ligne : on garde les prix connus

PORT = int(os.environ.get("SUIVI_FILAMENT_PORT", "47321"))
JETON_FICHIER = os.path.join(DOSSIER, ".jeton")
COMMANDE_SLICER = os.path.join(DOSSIER, "bobines")
VERROU = threading.Lock()
dernier_signe = time.time()
au_revoir = 0.0


# ----------------------------------------------------------------------------- installation du moteur

def installer_moteur():
    """Copie le moteur dans ~/SuiviFilament : le chemin reste valable même si l'app est déplacée."""
    change = False
    for f in ("suivi_filament.py", "configurer_slicer.py", "surveillant.py"):
        src, dst = os.path.join(RES, f), os.path.join(DOSSIER, f)
        if not os.path.exists(dst) or open(src, "rb").read() != open(dst, "rb").read():
            shutil.copy2(src, dst)
            change = True
    with open(os.path.join(RES, "bobines.modele"), encoding="utf-8") as fh:
        wrapper = fh.read().replace("@PYTHON@", sys.executable)
    if not os.path.exists(COMMANDE_SLICER) or open(COMMANDE_SLICER, encoding="utf-8").read() != wrapper:
        with open(COMMANDE_SLICER, "w", encoding="utf-8") as fh:
            fh.write(wrapper)
    os.chmod(COMMANDE_SLICER, 0o755)
    os.chmod(os.path.join(DOSSIER, "suivi_filament.py"), 0o755)
    if sys.platform == "darwin":
        # fichiers venus d'un zip téléchargé : retirer la quarantaine pour que le slicer puisse les lancer
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", DOSSIER], capture_output=True)
    if change and os.path.exists(AGENT_PLIST):
        activer_surveillance()          # nouvelle version du moteur : on relance le surveillant


# ----------------------------------------------------------------------------- surveillant (LaunchAgent)

AGENT = "local.suivifilament.surveillant"
AGENT_PLIST = os.path.expanduser(os.environ.get("SUIVI_FILAMENT_AGENT_PLIST",
                                                f"~/Library/LaunchAgents/{AGENT}.plist"))
ETAT_SURVEILLANT = os.path.join(DOSSIER, "surveillant.etat")


def _uid_gui():
    return f"gui/{os.getuid()}"


def activer_surveillance():
    """Installe et (re)lance le surveillant en arrière-plan, à chaque ouverture de session."""
    import plistlib
    script = os.path.join(DOSSIER, "surveillant.py")
    if sys.platform != "darwin":
        # hors macOS (développement / tests) : simple processus détaché
        arreter_surveillance()
        subprocess.Popen([sys.executable, script], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=open(os.path.join(DOSSIER, "surveillant.log"), "a"))
        open(AGENT_PLIST_DEV, "w").close()
        return
    os.makedirs(os.path.dirname(AGENT_PLIST), exist_ok=True)
    with open(AGENT_PLIST, "wb") as fh:
        plistlib.dump({
            "Label": AGENT,
            "ProgramArguments": [sys.executable, script],
            "EnvironmentVariables": {"PYTHONDONTWRITEBYTECODE": "1", "LANG": "fr_FR.UTF-8"},
            "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
            "StandardOutPath": os.path.join(DOSSIER, "surveillant.log"),
            "StandardErrorPath": os.path.join(DOSSIER, "surveillant.log"),
        }, fh)
    subprocess.run(["launchctl", "bootout", f"{_uid_gui()}/{AGENT}"], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", _uid_gui(), AGENT_PLIST], capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError("macOS a refusé de lancer la détection : " + (r.stderr.strip() or f"code {r.returncode}"))


def arreter_surveillance():
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "bootout", f"{_uid_gui()}/{AGENT}"], capture_output=True)
        if os.path.exists(AGENT_PLIST):
            os.remove(AGENT_PLIST)
    else:
        try:
            with open(ETAT_SURVEILLANT, encoding="utf-8") as fh:
                os.kill(json.load(fh)["pid"], 15)
        except Exception:
            pass
        if os.path.exists(AGENT_PLIST_DEV):
            os.remove(AGENT_PLIST_DEV)
    if os.path.exists(ETAT_SURVEILLANT):
        os.remove(ETAT_SURVEILLANT)


AGENT_PLIST_DEV = os.path.join(DOSSIER, ".surveillant-dev")   # marqueur « installé » hors macOS


def etat_surveillance():
    installee = os.path.exists(AGENT_PLIST if sys.platform == "darwin" else AGENT_PLIST_DEV)
    try:
        with open(ETAT_SURVEILLANT, encoding="utf-8") as fh:
            e = json.load(fh)
    except Exception:
        e = {}
    actif = bool(e) and time.time() - e.get("signe", 0) < 20
    return {"installee": installee, "active": installee and actif,
            "inaccessibles": e.get("inaccessibles", []), "exports": e.get("exports", [])}


# ----------------------------------------------------------------------------- état

def slicer_ouvert():
    try:
        r = subprocess.run(["pgrep", "-if", "ElegooSlicer.app/Contents/MacOS"], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def etat_slicer():
    bases = [b for m in cs.DOSSIERS for b in cs.glob.glob(os.path.join(cs.SUPPORT, m))]
    profils = []
    for f in cs.profils():
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        pp = d.get("post_process", [])
        pp = [pp] if isinstance(pp, str) else pp
        profils.append({"nom": d.get("name", os.path.basename(f)[:-5]),
                        "configure": any(COMMANDE_SLICER in s for s in pp)})
    return {"installe": bool(bases), "ouvert": slicer_ouvert(), "profils": profils,
            "lies": [p["nom"] for p in profils if p["configure"]],
            "commande": COMMANDE_SLICER, "dernier_appel": dernier_appel(),
            "surveillance": etat_surveillance()}


def dernier_appel():
    """Dernier passage d'ElegooSlicer d'après le journal du script : date et résultat."""
    try:
        with open(os.path.join(DOSSIER, "post_traitement.log"), encoding="utf-8", errors="replace") as fh:
            lignes = fh.read().splitlines()[-50:]
    except OSError:
        return None
    for i in range(len(lignes) - 1, -1, -1):
        if "appel du slicer" in lignes[i] or "G-code détecté" in lignes[i]:
            suite = lignes[i + 1].split("] ", 1)[-1].strip() if i + 1 < len(lignes) else ""
            return {"date": lignes[i][1:17], "resultat": suite}
    return None


def retirer_ancien_lien(silencieux=False):
    """Retire l'ancien script de post-traitement des profils (il pouvait bloquer les impressions)."""
    if not any(p["configure"] for p in etat_slicer()["profils"]):
        return
    if slicer_ouvert():
        if silencieux:
            return
        raise ValueError("Quitte d'abord ElegooSlicer (⌘Q), sinon il remettrait l'ancien réglage en se fermant.")
    r = subprocess.run([sys.executable, os.path.join(DOSSIER, "configurer_slicer.py"), "--retirer", COMMANDE_SLICER],
                       capture_output=True, text=True)
    if r.returncode != 0 and not silencieux:
        raise ValueError(r.stdout.strip() or r.stderr.strip() or "Échec du retrait")


def etat():
    d = sf.charger()
    prix = {b["id"]: b.get("prix_kg") for b in d["bobines"]}
    mois = dt.date.today().strftime("%Y-%m")
    total = sum(h["total_g"] for h in d["historique"])
    total_mois = sum(h["total_g"] for h in d["historique"] if h["date"].startswith(mois))
    cout = sum(x["g"] / 1000 * (prix.get(x["bobine"]) or 0) for h in d["historique"] for x in h["deductions"])
    noms = {b["id"]: b["nom"] for b in d["bobines"]}
    histo = []
    for h in reversed(d["historique"][-200:]):
        histo.append({**{k: h.get(k) for k in ("date", "tache", "total_g", "temps")},
                      "deductions": [{**x, "nom": noms.get(x["bobine"], f"#{x['bobine']} (supprimée)")}
                                     for x in h["deductions"]]})
    return {
        "bobines": d["bobines"], "actives": d["actives"], "seuil": d["seuil_alerte_g"],
        "historique": histo,
        "stats": {"total_g": round(total, 1), "mois_g": round(total_mois, 1),
                  "cout": round(cout, 2), "impressions": len(d["historique"]),
                  "stock_g": round(sum(max(b["reste_g"], 0) for b in d["bobines"]), 1)},
        "slicer": etat_slicer(),
        "fichier": sf.DATA,
    }


# ----------------------------------------------------------------------------- actions

def nombre(v, defaut=None):
    if v in (None, ""):
        return defaut
    return float(str(v).replace(",", "."))


def trouver(d, ident):
    for b in d["bobines"]:
        if b["id"] == ident:
            return b
    raise ValueError("Bobine introuvable")


def action(chemin, corps):
    morceaux = chemin.strip("/").split("/")[1:]          # après "api"
    with VERROU:
        d = sf.charger()
        if morceaux == ["bobines"]:
            nom = (corps.get("nom") or "").strip()
            if not nom:
                raise ValueError("Donne un nom à la bobine")
            poids = nombre(corps.get("poids"), 1000)
            b = {"id": d["prochain_id"], "nom": nom, "matiere": corps.get("matiere") or "PLA",
                 "couleur": corps.get("couleur") or "#888888", "poids_net_g": poids,
                 "reste_g": nombre(corps.get("reste"), poids), "tare_g": nombre(corps.get("tare")),
                 "prix_kg": nombre(corps.get("prix")), "ajoutee_le": sf.maintenant()}
            ref = corps.get("catalogue")
            if isinstance(ref, dict) and ref.get("gamme"):
                b["catalogue"] = {k: str(ref.get(k, ""))[:120] for k in ("gamme", "couleur", "format", "url", "maj")}
            d["bobines"].append(b)
            d["prochain_id"] += 1
            if corps.get("emplacement"):
                d["actives"][str(int(corps["emplacement"]))] = b["id"]
        elif len(morceaux) == 3 and morceaux[0] == "bobines":
            b = trouver(d, int(morceaux[1]))
            op = morceaux[2]
            if op == "modifier":
                for k in ("nom", "matiere", "couleur"):
                    if corps.get(k) not in (None, ""):
                        b[k] = corps[k]
                for k, cle in (("prix", "prix_kg"), ("tare", "tare_g"), ("poids", "poids_net_g"), ("reste", "reste_g")):
                    if k in corps:
                        b[cle] = nombre(corps[k], b.get(cle))
            elif op == "peser":
                tare = nombre(corps.get("tare"), b.get("tare_g"))
                if tare is None:
                    raise ValueError("Indique le poids de la bobine vide (tare)")
                b["tare_g"] = tare
                b["reste_g"] = round(nombre(corps.get("brut")) - tare, 1)
            elif op == "activer":
                emp = corps.get("emplacement")
                d["actives"] = {k: v for k, v in d["actives"].items() if v != b["id"]}
                if emp:
                    d["actives"][str(int(emp))] = b["id"]
            elif op == "supprimer":
                d["bobines"].remove(b)
                d["actives"] = {k: v for k, v in d["actives"].items() if v != b["id"]}
            else:
                raise ValueError("Action inconnue")
        elif morceaux == ["annuler"]:
            if not d["historique"]:
                raise ValueError("Historique vide")
            h = d["historique"].pop()
            for x in h["deductions"]:
                for b in d["bobines"]:
                    if b["id"] == x["bobine"]:
                        b["reste_g"] = round(b["reste_g"] + x["g"], 2)
        elif morceaux == ["seuil"]:
            d["seuil_alerte_g"] = nombre(corps.get("grammes"), 100)
        elif morceaux == ["surveillance", "activer"]:
            activer_surveillance()
            retirer_ancien_lien(silencieux=True)
            for _ in range(20):                  # laisser au surveillant le temps de donner signe de vie
                if etat_surveillance()["active"]:
                    break
                time.sleep(0.25)
            return
        elif morceaux == ["surveillance", "desactiver"]:
            arreter_surveillance()
            return
        elif morceaux == ["slicer", "retirer"]:
            retirer_ancien_lien()
            return
        elif morceaux == ["slicer", "configurer"]:
            if slicer_ouvert():
                raise ValueError("Quitte d'abord ElegooSlicer (⌘Q), sinon il écraserait le réglage en se fermant.")
            r = subprocess.run([sys.executable, os.path.join(DOSSIER, "configurer_slicer.py"), COMMANDE_SLICER],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise ValueError(r.stdout.strip() or r.stderr.strip() or "Échec de la configuration")
            return
        else:
            raise ValueError("Requête inconnue")
        sf.sauver(d)


# ----------------------------------------------------------------------------- HTTP

class Gestion(BaseHTTPRequestHandler):
    server_version = "SuiviFilament"

    def log_message(self, *a):
        pass

    def _envoyer(self, code, data, type_="application/json; charset=utf-8"):
        corps = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corps)

    def _autorise(self):
        # jeton aléatoire : aucun autre site ouvert dans le navigateur ne peut piloter l'app
        return self.headers.get("X-Jeton") == JETON or urlparse(self.path).query == "t=" + JETON

    def do_GET(self):
        global dernier_signe
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            if urlparse(self.path).query != "t=" + JETON:
                return self._envoyer(403, b"Ouvre l'application Suivi Filament.", "text/plain; charset=utf-8")
            html = open(os.path.join(RES, "index.html"), "rb").read().replace(b"@JETON@", JETON.encode())
            return self._envoyer(200, html, "text/html; charset=utf-8")
        if p == "/api/bonjour":
            return self._envoyer(200, {"app": "SuiviFilament"})
        if not self._autorise():
            return self._envoyer(403, {"erreur": "interdit"})
        if p == "/api/etat":
            dernier_signe = time.time()
            return self._envoyer(200, etat())
        if p == "/api/catalogue":
            return self._envoyer(200, lire_catalogue())
        self._envoyer(404, {"erreur": "introuvable"})

    def do_POST(self):
        global dernier_signe, au_revoir
        if not self._autorise():
            return self._envoyer(403, {"erreur": "interdit"})
        p = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            corps = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except ValueError:
            corps = {}
        dernier_signe = time.time()
        if p == "/api/signe":
            au_revoir = 0.0
            return self._envoyer(200, {"ok": True})
        if p == "/api/au-revoir":
            au_revoir = time.time()
            return self._envoyer(200, {"ok": True})
        if p == "/api/catalogue/actualiser":
            try:
                return self._envoyer(200, actualiser_catalogue())
            except Exception:
                return self._envoyer(502, {"erreur": "Impossible de joindre la boutique Elegoo (connexion ?). "
                                                     "Les prix connus sont conservés."})
        if p == "/api/quitter":
            self._envoyer(200, {"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        try:
            action(p, corps)
            self._envoyer(200, etat())
        except (ValueError, KeyError, TypeError) as e:
            self._envoyer(400, {"erreur": str(e)})


def surveiller(serveur):
    """Ferme l'app quand l'onglet est fermé (signe de vie absent)."""
    while True:
        time.sleep(5)
        maintenant = time.time()
        if au_revoir and maintenant - au_revoir > 15 and dernier_signe <= au_revoir + 1:
            break
        if maintenant - dernier_signe > 180:     # onglet en arrière-plan : signes ralentis par le navigateur
            break
    serveur.shutdown()


def ouvrir(url):
    if os.environ.get("SUIVI_FILAMENT_SANS_NAVIGATEUR"):
        print(url, flush=True)
        return
    subprocess.run(["open", url])


def deja_lance():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/bonjour", timeout=1) as r:
            return json.load(r).get("app") == "SuiviFilament"
    except Exception:
        return False


if __name__ == "__main__":
    installer_moteur()
    if deja_lance() and os.path.exists(JETON_FICHIER):
        ouvrir(f"http://127.0.0.1:{PORT}/?t={open(JETON_FICHIER).read().strip()}")
        sys.exit(0)
    JETON = secrets.token_urlsafe(24)
    fd = os.open(JETON_FICHIER, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.write(fd, JETON.encode()); os.close(fd)
    try:
        serveur = ThreadingHTTPServer(("127.0.0.1", PORT), Gestion)
    except OSError:
        serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
    PORT = serveur.server_address[1]
    threading.Thread(target=surveiller, args=(serveur,), daemon=True).start()
    threading.Thread(target=actualiser_si_ancien, daemon=True).start()
    ouvrir(f"http://127.0.0.1:{PORT}/?t={JETON}")
    serveur.serve_forever()
