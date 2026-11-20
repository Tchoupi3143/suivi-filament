# SPDX-License-Identifier: GPL-3.0-or-later
"""
Connexion automatique au compte bancaire (DSP2) via Enable Banking.

Enable Banking est un intermédiaire agréé qui donne accès, en lecture seule, aux
opérations des banques européennes (dont chaque Banque Populaire régionale).
Son « mode restreint » est gratuit pour un usage personnel non commercial :
l'application ne peut lire que les comptes que tu as toi-même reliés.

Authentification : jeton JWT signé RS256 avec la clé privée de ton application
(fichier .pem téléchargé depuis le panneau de contrôle Enable Banking).
La signature RSA est faite ici en Python pur : aucune dépendance.
"""
import base64
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("SUIVI_LOYERS_API_BANQUE", "https://api.enablebanking.com")   # surchargé par les tests


class ErreurBanque(RuntimeError):
    pass


# --------------------------------------------------------------------------- clé RSA (DER minimal)

def _der(octets, i=0):
    """Lit un élément DER à la position i : (tag, contenu, position suivante)."""
    tag = octets[i]
    n = octets[i + 1]
    i += 2
    if n & 0x80:
        k = n & 0x7F
        n = int.from_bytes(octets[i:i + k], "big")
        i += k
    return tag, octets[i:i + n], i + n


def _sequence(octets):
    tag, contenu, _ = _der(octets)
    if tag != 0x30:
        raise ErreurBanque("Clé privée illisible (SEQUENCE attendue)")
    elements, i = [], 0
    while i < len(contenu):
        t, c, i = _der(contenu, i)
        elements.append((t, c))
    return elements


def charger_cle(pem):
    """Clé privée RSA PEM (PKCS#1 « RSA PRIVATE KEY » ou PKCS#8 « PRIVATE KEY ») -> (n, d)."""
    texte = pem.decode() if isinstance(pem, bytes) else pem
    m = re.search(r"-----BEGIN (RSA )?PRIVATE KEY-----(.*?)-----END", texte, re.S)
    if not m:
        if "ENCRYPTED" in texte:
            raise ErreurBanque("Clé privée chiffrée par mot de passe : non prise en charge")
        raise ErreurBanque("Ce fichier n'est pas une clé privée RSA (.pem)")
    der = base64.b64decode("".join(m.group(2).split()))
    elements = _sequence(der)
    if not m.group(1):                                   # PKCS#8 : la clé PKCS#1 est dans un OCTET STRING
        octet = next((c for t, c in elements if t == 0x04), None)
        if octet is None:
            raise ErreurBanque("Clé PKCS#8 illisible")
        elements = _sequence(octet)
    entiers = [int.from_bytes(c, "big") for t, c in elements if t == 0x02]
    if len(entiers) < 4:
        raise ErreurBanque("Clé RSA incomplète")
    return entiers[1], entiers[3]                        # version, n, e, d, …


_SHA256_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def signer_rs256(message, n, d):
    k = (n.bit_length() + 7) // 8
    t = _SHA256_INFO + hashlib.sha256(message).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")


def _b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def jeton(app_id, cle_pem, duree=3600):
    n, d = charger_cle(cle_pem)
    maintenant = int(time.time())
    entete = {"typ": "JWT", "alg": "RS256", "kid": app_id}
    charge = {"iss": "enablebanking.com", "aud": "api.enablebanking.com", "iat": maintenant, "exp": maintenant + duree}
    signe = _b64url(json.dumps(entete, separators=(",", ":")).encode()) + "." + \
        _b64url(json.dumps(charge, separators=(",", ":")).encode())
    return signe + "." + _b64url(signer_rs256(signe.encode(), n, d))


# --------------------------------------------------------------------------- appels

def appel(conf, methode, chemin, corps=None, params=None):
    url = API + chemin + ("?" + urllib.parse.urlencode(params) if params else "")
    requete = urllib.request.Request(url, method=methode, data=json.dumps(corps).encode() if corps is not None else None)
    requete.add_header("Authorization", "Bearer " + jeton(conf["app_id"], conf["cle"]))
    requete.add_header("Accept", "application/json")
    if corps is not None:
        requete.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(requete, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e)
            texte = detail.get("message") or detail.get("error") or json.dumps(detail)[:300]
            code = detail.get("error") or ""
        except Exception:
            texte, code = e.reason, ""
        raise ErreurBanque(f"Enable Banking ({e.code}) : {texte}" + (f" [{code}]" if code and code not in texte else ""))
    except urllib.error.URLError as e:
        raise ErreurBanque(f"Enable Banking injoignable : {e.reason}")


def banques(conf, pays="FR"):
    r = appel(conf, "GET", "/aspsps", params={"country": pays, "psu_type": "personal"})
    return sorted(({"name": a["name"], "country": a["country"],
                    "max_secondes": a.get("maximum_consent_validity")} for a in r.get("aspsps", [])),
                  key=lambda a: a["name"].lower())


def demarrer(conf, nom_banque, pays="FR", jours=180):
    """Renvoie (url de la banque, state). La personne s'y authentifie puis est renvoyée sur redirect_url."""
    max_s = next((b["max_secondes"] for b in banques(conf, pays) if b["name"] == nom_banque), None)
    secondes = min(jours * 86400, max_s or jours * 86400) - 600
    fin = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=secondes)
    state = secrets.token_urlsafe(16)
    r = appel(conf, "POST", "/auth", {
        "access": {"valid_until": fin.isoformat(timespec="microseconds")},
        "aspsp": {"name": nom_banque, "country": pays}, "state": state,
        "redirect_url": conf["redirect_url"], "psu_type": "personal", "language": "fr"})
    return r["url"], state


def code_depuis(adresse, state_attendu=None):
    """Accepte l'adresse complète de la page de retour, ou le code seul."""
    adresse = (adresse or "").strip()
    if "code=" not in adresse and "error=" not in adresse:
        if re.fullmatch(r"[A-Za-z0-9._~-]{8,}", adresse):
            return adresse
        raise ErreurBanque("Colle l'adresse complète de la page sur laquelle la banque t'a renvoyé")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(adresse).query or adresse.split("?", 1)[-1])
    if q.get("error"):
        raise ErreurBanque("La banque a refusé : " + (q.get("error_description") or q["error"])[0])
    if state_attendu and q.get("state", [state_attendu])[0] != state_attendu:
        raise ErreurBanque("Ce retour ne correspond pas à la dernière demande de connexion : recommence")
    return q["code"][0]


def terminer(conf, code):
    r = appel(conf, "POST", "/sessions", {"code": code})
    comptes = []
    for a in r.get("accounts", []):
        if isinstance(a, str):
            comptes.append({"uid": a, "nom": "", "iban": ""})
        else:
            comptes.append({"uid": a["uid"], "nom": a.get("name") or a.get("product") or "",
                            "iban": (a.get("account_id") or {}).get("iban") or ""})
    return {"session_id": r["session_id"], "comptes": comptes,
            "valide_jusqu": ((r.get("access") or {}).get("valid_until") or "")[:10]}


def operations(conf, compte_uid, date_from):
    """Opérations comptabilisées depuis date_from (AAAA-MM-JJ), au format de releves.lire()."""
    ops, cle = [], None
    for _ in range(50):
        params = {"date_from": date_from}
        if cle:
            params["continuation_key"] = cle
        r = appel(conf, "GET", f"/accounts/{urllib.parse.quote(compte_uid)}/transactions", params=params)
        for t in r.get("transactions", []):
            if t.get("status") not in (None, "BOOK"):
                continue                                   # en attente, rejetée… : pas encore un paiement
            montant_txt = (t.get("transaction_amount") or {}).get("amount")
            date = t.get("booking_date") or t.get("value_date") or t.get("transaction_date")
            if montant_txt is None or not date:
                continue
            centimes = int(round(float(montant_txt) * 100))
            centimes = -abs(centimes) if t.get("credit_debit_indicator") == "DBIT" else abs(centimes)
            payeur = (t.get("debtor") or {}).get("name") if centimes > 0 else (t.get("creditor") or {}).get("name")
            libelle = " ".join(x for x in [payeur or ""] + list(t.get("remittance_information") or [])
                               + [t.get("note") or ""] if x).strip()
            ops.append({"date": date[:10], "montant": centimes, "libelle": re.sub(r"\s+", " ", libelle),
                        "ref": t.get("entry_reference") or None})
        cle = r.get("continuation_key")
        if not cle:
            break
    return ops
