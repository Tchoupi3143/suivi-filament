#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Suivi Loyers — moteur.

Importe les relevés du compte bancaire qui reçoit les loyers, reconnaît les
virements de chaque locataire, calcule ce qui est payé mois par mois et émet
(puis envoie par e-mail) la quittance dès qu'un mois est réglé en totalité.

    python3 loyers.py scan [relevé.ofx|csv|xml ...] [--sans-envoi]
    python3 loyers.py statut [AAAA-MM]

« scan » récupère les nouvelles opérations directement auprès de la banque si la
connexion bancaire est configurée, et traite aussi tout fichier déposé dans
~/SuiviLoyers/a-importer/ (rangé ensuite dans importes/). C'est la commande à
planifier (cron, launchd, Planificateur de tâches) une fois par jour.

Données : ~/SuiviLoyers/donnees.json (dossier modifiable avec SUIVI_LOYERS_DOSSIER).
"""
import calendar
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import banque                # noqa: E402
import envoi                 # noqa: E402
import quittance as qt       # noqa: E402
import releves               # noqa: E402

DOSSIER = os.path.expanduser(os.environ.get("SUIVI_LOYERS_DOSSIER", "~/SuiviLoyers"))
DATA = os.path.join(DOSSIER, "donnees.json")
BOITE = os.path.join(DOSSIER, "a-importer")
RANGES = os.path.join(DOSSIER, "importes")
QUITTANCES = os.path.join(DOSSIER, "quittances")
HORIZON_AVANCE = 12          # mois payés d'avance acceptés

MODELE_SUJET = "Quittance de loyer — {periode}"
MODELE_TEXTE = """Bonjour {locataire},

Votre paiement de {montant} a bien été reçu le {date_paiement}.
Vous trouverez ci-joint la quittance de loyer pour {periode}.

Logement : {logement}

Bien cordialement,
{bailleur}
"""
MODELE_RELANCE = """Bonjour {locataire},

Sauf erreur de notre part, le loyer de {periode} ({montant}), payable le {echeance},
n'a pas encore été reçu{deja}.

Si le virement vient d'être fait, merci de ne pas tenir compte de ce message.

Bien cordialement,
{bailleur}
"""


def aujourdhui():
    return dt.date.fromisoformat(os.environ["SUIVI_LOYERS_AUJOURDHUI"]) if os.environ.get(
        "SUIVI_LOYERS_AUJOURDHUI") else dt.date.today()


def maintenant():
    return aujourdhui().isoformat() + dt.datetime.now().strftime(" %H:%M")


# --------------------------------------------------------------------------- stockage

def vierge():
    return {
        "version": 1,
        "bailleur": {"nom": "", "signataire": "", "adresse": "", "ville": "", "email": ""},
        "smtp": {"hote": "", "port": 465, "securite": "ssl", "utilisateur": "", "expediteur": "",
                 "nom_expediteur": "", "copie_bailleur": True},
        "reglages": {"envoi_auto": True, "jours_grace": 5, "sujet": MODELE_SUJET, "texte": MODELE_TEXTE},
        "banque": {"app_id": "", "redirect_url": "https://example.com/redirect", "banque": "", "pays": "FR",
                   "session_id": "", "comptes": [], "compte": "", "valide_jusqu": "", "derniere_synchro": "",
                   "alerte_expiration": ""},
        "baux": [], "operations": [], "quittances": [], "journal": [], "prochain_bail": 1,
    }


def charger():
    try:
        with open(DATA, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return vierge()
    base = vierge()
    for k, v in base.items():
        if isinstance(v, dict):
            d[k] = {**v, **d.get(k, {})}
        else:
            d.setdefault(k, v)
    return d


def sauver(d):
    os.makedirs(DOSSIER, exist_ok=True)
    d["journal"] = d["journal"][-500:]
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, DATA)


def noter(d, texte):
    d["journal"].append({"date": maintenant(), "texte": texte})


# --------------------------------------------------------------------------- périodes

def mois(date_iso):
    return date_iso[:7]


def mois_suivant(p, n=1):
    a, m = map(int, p.split("-"))
    m += n
    a, m = a + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{a:04d}-{m:02d}"


def plage(debut, fin):
    p = debut
    while p <= fin:
        yield p
        p = mois_suivant(p)


def du(bail, periode):
    """(loyer, charges) en centimes applicables pour la période (révisions comprises)."""
    actuel = None
    for m in sorted(bail["montants"], key=lambda x: x["depuis"]):
        if m["depuis"] <= periode:
            actuel = m
    actuel = actuel or sorted(bail["montants"], key=lambda x: x["depuis"])[0]
    return actuel["loyer"], actuel["charges"]


def echeance(bail, periode):
    a, m = map(int, periode.split("-"))
    return dt.date(a, m, min(int(bail.get("jour_echeance") or 1), calendar.monthrange(a, m)[1]))


# --------------------------------------------------------------------------- rapprochement

def normaliser(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return " " + re.sub(r"[^A-Z0-9]+", " ", s).strip() + " "


def motifs(bail):
    m = [x for x in bail.get("motifs", []) if x.strip()]
    return m or [bail["locataire"]]


def correspond(bail, libelle):
    lib = normaliser(libelle)
    for motif in motifs(bail):
        mots = normaliser(motif).split()
        if mots and all(f" {w} " in lib for w in mots):
            return True
    return False


def actif_a(bail, periode):
    return bail["debut"] <= mois_suivant(periode) and (not bail.get("fin") or periode <= bail["fin"])


def rapprocher(d):
    """Affecte les crédits non traités aux baux. Renvoie la liste des opérations affectées."""
    nouvelles = []
    for op in d["operations"]:
        if op["montant"] <= 0 or op.get("bail") or op.get("ignoree") or op.get("manuel_libre"):
            continue
        p = mois(op["date"])
        candidats = [b for b in d["baux"] if b.get("actif", True) and actif_a(b, p) and correspond(b, op["libelle"])]
        op.pop("suggestion", None)
        if len(candidats) == 1:
            op["bail"], op["methode"] = candidats[0]["id"], "libellé"
            nouvelles.append(op)
            continue
        # pas (ou trop) de correspondance sur le nom : simple suggestion d'après le montant, à confirmer
        pool = candidats or [b for b in d["baux"] if b.get("actif", True) and actif_a(b, p)]
        par_montant = [b for b in pool if sum(du(b, p)) == op["montant"]]
        if len(par_montant) == 1:
            op["suggestion"] = par_montant[0]["id"]
    return nouvelles


def affecter(d, op_id, bail_id):
    op = trouver_op(d, op_id)
    if bail_id in (None, "", 0):
        op.pop("bail", None)
        op["manuel_libre"] = True          # ne plus le réaffecter automatiquement
    else:
        trouver_bail(d, int(bail_id))
        op["bail"], op["methode"] = int(bail_id), "manuel"
        op.pop("manuel_libre", None)
        op.pop("ignoree", None)
    op.pop("suggestion", None)


# --------------------------------------------------------------------------- calcul des soldes

def situation(d, bail, jusqua=None):
    """
    Répartit les paiements du bail sur les mois, du plus ancien au plus récent.
    Renvoie {periode: {...}} et le trop-perçu éventuel.
    """
    courant = mois(aujourdhui().isoformat())
    fin = bail.get("fin") or mois_suivant(courant, HORIZON_AVANCE)
    fin = min(fin, mois_suivant(courant, HORIZON_AVANCE))
    periodes = list(plage(bail["debut"], fin))
    etat = {}
    for p in periodes:
        loyer, charges = du(bail, p)
        etat[p] = {"periode": p, "loyer": loyer, "charges": charges, "du": loyer + charges, "paye": 0,
                   "date_paiement": None, "operations": [], "details": [],
                   "reporte": 0,          # part des virements de ce mois reportée sur les mois suivants
                   "avance_recue": 0}     # part payée par un virement d'un mois précédent (excédent, avance)
    ops = sorted((o for o in d["operations"] if o.get("bail") == bail["id"] and not o.get("ignoree")),
                 key=lambda o: (o["date"], o["id"]))
    reste_total = 0
    for op in ops:
        reste = op["montant"]
        if reste < 0:                         # rejet / remboursement : on retire du dernier mois payé
            reste_total += reste
            continue
        # imputation : d'abord le mois où le virement est reçu, puis un éventuel arriéré (le plus ancien
        # d'abord), puis les mois suivants (avance). Ainsi un petit manque sur un mois reste sur ce mois
        # et ne décale pas tous les mois suivants (ni ne bloque leurs quittances).
        cible = min(max(mois(op["date"]), periodes[0]), periodes[-1]) if periodes else None
        ordre = ([cible] + [p for p in periodes if p < cible] + [p for p in periodes if p > cible]) if cible else []
        parts = []                            # (mois, montant) alimentés par ce virement
        for p in ordre:
            if reste <= 0:
                break
            e = etat[p]
            part = min(reste, e["du"] - e["paye"])
            if part > 0:
                e["paye"] += part
                e["operations"].append(op["id"])
                reste -= part
                parts.append((e, part))
                if e["paye"] >= e["du"]:
                    e["date_paiement"] = op["date"]
        for e, part in parts[1:]:
            e["avance_recue"] += part
        if parts:
            parts[0][0]["reporte"] += sum(part for _, part in parts[1:]) + reste
        # virement réparti sur plusieurs mois (arriéré complété, excédent reporté) : on le dit sur chaque mois
        if len(parts) > 1 or (parts and reste):
            for e, part in parts:
                e["details"].append({"date": op["date"], "montant": op["montant"], "part": part, "reste": reste,
                                     "autres": [{"periode": x["periode"], "part": p2} for x, p2 in parts if x is not e]})
        reste_total += reste
    # retraits (montants négatifs affectés au bail) : on « dé-paie » en partant de la fin
    j = len(periodes) - 1
    while reste_total < 0 and j >= 0:
        e = etat[periodes[j]]
        retrait = min(e["paye"], -reste_total)
        e["paye"] -= retrait
        reste_total += retrait
        if e["paye"] < e["du"]:
            e["date_paiement"] = None
        j -= 1
    today = aujourdhui()
    grace = int(d["reglages"].get("jours_grace", 5))
    for p, e in etat.items():
        if e["paye"] >= e["du"]:
            e["statut"] = "payé" if p <= courant else "avance"
        elif p > courant:
            e["statut"] = "futur"
        elif today > echeance(bail, p) + dt.timedelta(days=grace):
            e["statut"] = "partiel en retard" if e["paye"] else "en retard"
        else:
            e["statut"] = "partiel" if e["paye"] else "attendu"
        e["echeance"] = echeance(bail, p).isoformat()
    return etat, max(reste_total, 0)


# --------------------------------------------------------------------------- quittances

def trouver_bail(d, ident):
    for b in d["baux"]:
        if b["id"] == ident:
            return b
    raise ValueError("Bail introuvable")


def trouver_op(d, ident):
    for o in d["operations"]:
        if o["id"] == ident:
            return o
    raise ValueError("Opération introuvable")


def trouver_quittance(d, bail_id, periode, type_="quittance"):
    for q in d["quittances"]:
        if q["bail"] == bail_id and q["periode"] == periode and q.get("type", "quittance") == type_:
            return q
    return None


def chemin_pdf(q):
    return os.path.join(QUITTANCES, q["fichier"])


def fabriquer(d, bail, e, type_="quittance"):
    """Crée (ou recrée) le PDF d'une quittance ou d'un reçu ; renvoie l'entrée enregistrée."""
    q = trouver_quittance(d, bail["id"], e["periode"], type_)
    numero = f"{e['periode']}-{bail['id']:02d}" + ("" if type_ == "quittance" else "-R")
    nom_fic = re.sub(r"[^A-Za-z0-9]+", "-", normaliser(bail["locataire"]).title()).strip("-")
    rel = os.path.join(f"{bail['id']:02d}-{nom_fic or 'locataire'}",
                       f"{'Quittance' if type_ == 'quittance' else 'Recu'}-{e['periode']}.pdf")
    date_paiement = e["date_paiement"] or (max(o["date"] for o in d["operations"] if o["id"] in e["operations"])
                                           if e["operations"] else aujourdhui().isoformat())
    pdf = qt.generer(d["bailleur"], bail, e["periode"], e["loyer"], e["charges"], e["paye"], date_paiement, numero,
                     emise_le=aujourdhui().isoformat())
    os.makedirs(os.path.dirname(os.path.join(QUITTANCES, rel)), exist_ok=True)
    with open(os.path.join(QUITTANCES, rel), "wb") as f:
        f.write(pdf)
    infos = {"bail": bail["id"], "periode": e["periode"], "type": type_, "numero": numero, "fichier": rel,
             "montant": e["paye"] if type_ != "quittance" else e["du"], "date_paiement": date_paiement,
             "emise_le": aujourdhui().isoformat()}
    if q:
        q.update(infos)
    else:
        q = {**infos, "envoyee_le": None, "erreur": None}
        d["quittances"].append(q)
    return q


def valeurs_modele(d, bail, q):
    return {"locataire": bail["locataire"], "periode": qt.libelle_periode(q["periode"]),
            "montant": qt.euros(q["montant"]), "date_paiement": qt.date_longue(q["date_paiement"]),
            "logement": " — ".join((bail.get("logement") or "").splitlines()),
            "bailleur": d["bailleur"].get("signataire") or d["bailleur"].get("nom", "")}


def envoyer_quittance(d, q):
    bail = trouver_bail(d, q["bail"])
    if not bail.get("email"):
        raise RuntimeError(f"Pas d'adresse e-mail pour {bail['locataire']}")
    v = valeurs_modele(d, bail, q)
    r = d["reglages"]
    if q["type"] == "quittance":
        sujet = (r.get("sujet") or MODELE_SUJET).format(**v)
        texte = (r.get("texte") or MODELE_TEXTE).format(**v)
    else:
        sujet = f"Reçu de paiement partiel — {v['periode']}"
        texte = (f"Bonjour {v['locataire']},\n\nNous avons bien reçu {v['montant']} pour le loyer de "
                 f"{v['periode']}. Vous trouverez ci-joint le reçu correspondant ; la quittance vous sera "
                 f"envoyée dès le règlement complet.\n\nBien cordialement,\n{v['bailleur']}\n")
    with open(chemin_pdf(q), "rb") as f:
        pdf = f.read()
    copie = d["bailleur"].get("email") if d["smtp"].get("copie_bailleur") else None
    envoi.envoyer(d["smtp"], DOSSIER, bail["email"], sujet, texte, [(os.path.basename(q["fichier"]), pdf)], copie)
    q["envoyee_le"], q["erreur"] = maintenant(), None
    noter(d, f"{'Quittance' if q['type'] == 'quittance' else 'Reçu'} {v['periode']} envoyé(e) à {bail['email']}")


def relancer(d, bail, periode):
    etat, _ = situation(d, bail)
    e = etat[periode]
    v = {"locataire": bail["locataire"], "periode": qt.libelle_periode(periode), "montant": qt.euros(e["du"]),
         "echeance": qt.date_longue(e["echeance"]),
         "deja": f" (seuls {qt.euros(e['paye'])} ont été reçus)" if e["paye"] else "",
         "bailleur": d["bailleur"].get("signataire") or d["bailleur"].get("nom", "")}
    copie = d["bailleur"].get("email") if d["smtp"].get("copie_bailleur") else None
    envoi.envoyer(d["smtp"], DOSSIER, bail["email"], f"Loyer de {v['periode']}", MODELE_RELANCE.format(**v),
                  copie=copie)
    bail.setdefault("relances", {})[periode] = maintenant()
    noter(d, f"Relance {v['periode']} envoyée à {bail['locataire']}")


def emettre(d, envoyer=True):
    """
    Pour chaque mois entièrement réglé et commencé : génère la quittance si elle n'existe pas,
    puis l'envoie (envoi automatique limité au mois courant et au précédent, pour ne pas
    inonder un locataire de vieilles quittances lors du premier import).
    Renvoie un compte rendu.
    """
    courant = mois(aujourdhui().isoformat())
    limite_auto = mois_suivant(courant, -1)
    cr = {"generees": [], "envoyees": [], "erreurs": []}
    for bail in d["baux"]:
        etat, _ = situation(d, bail)
        for p, e in etat.items():
            if p > courant or e["paye"] < e["du"]:
                continue
            q = trouver_quittance(d, bail["id"], p)
            if q and q["montant"] == e["du"] and q["date_paiement"] == e["date_paiement"]:
                pass
            else:
                q = fabriquer(d, bail, e)
                cr["generees"].append(f"{bail['locataire']} {p}")
                noter(d, f"Quittance {qt.libelle_periode(p)} générée pour {bail['locataire']}")
            auto = (envoyer and d["reglages"].get("envoi_auto", True) and envoi.configure(d["smtp"])
                    and bail.get("email") and bail.get("envoi_auto", True) and p >= limite_auto)
            if not q["envoyee_le"] and auto:
                try:
                    envoyer_quittance(d, q)
                    cr["envoyees"].append(f"{bail['locataire']} {p}")
                except Exception as ex:          # réseau, mot de passe… : on réessaiera au prochain scan
                    q["erreur"] = str(ex)[:300]
                    cr["erreurs"].append(f"{bail['locataire']} {p} : {ex}")
                    noter(d, f"Échec d'envoi de la quittance {p} à {bail['locataire']} : {ex}")
    return cr


# --------------------------------------------------------------------------- import

def identifiant(op, n):
    if op.get("ref"):
        return "r:" + hashlib.sha1(f"{op['ref']}|{op['date']}|{op['montant']}".encode()).hexdigest()[:16]
    cle = f"{op['date']}|{op['montant']}|{normaliser(op['libelle']).strip()}|{n}"
    return "h:" + hashlib.sha1(cle.encode()).hexdigest()[:16]


def importer(d, octets, nom=""):
    """Ajoute les opérations du relevé (doublons ignorés). Renvoie (nouvelles, deja_connues)."""
    return ajouter_operations(d, releves.lire(octets, nom), nom)


def ajouter_operations(d, ops, nom):
    connus = {o["id"] for o in d["operations"]}
    vus, nouvelles, deja = {}, 0, 0
    for op in ops:
        base = (op["date"], op["montant"], normaliser(op["libelle"]))
        vus[base] = vus.get(base, 0) + 1            # deux virements identiques le même jour
        ident = identifiant(op, vus[base])
        if ident in connus:
            deja += 1
            continue
        connus.add(ident)
        nouvelle = {"id": ident, "date": op["date"], "montant": op["montant"], "libelle": op["libelle"][:200],
                    "source": os.path.basename(nom)[:80], "importee_le": maintenant()}
        # même opération déjà importée depuis un AUTRE relevé (ex. export CSV puis OFX : libellés différents)
        jumelle = next((o for o in d["operations"] if o["date"] == op["date"] and o["montant"] == op["montant"]
                        and o.get("source") not in (nouvelle["source"], "manuel") and not o.get("doublon_de")), None)
        if jumelle and op["montant"] > 0:
            nouvelle.update(ignoree=True, doublon_de=jumelle["id"])
        d["operations"].append(nouvelle)
        nouvelles += 1
    d["operations"].sort(key=lambda o: o["date"])
    if nouvelles or nom != SOURCE_BANQUE:
        noter(d, f"Import {os.path.basename(nom) or 'relevé'} : {nouvelles} nouvelle(s) opération(s), {deja} déjà connue(s)")
    return nouvelles, deja


# --------------------------------------------------------------------------- connexion bancaire

SOURCE_BANQUE = "banque"
CLE_BANQUE = os.path.join(DOSSIER, "enablebanking.pem")


def conf_banque(d):
    b = d["banque"]
    try:
        with open(CLE_BANQUE, encoding="utf-8") as f:
            cle = f.read()
    except OSError:
        cle = ""
    return {"app_id": b.get("app_id"), "cle": cle, "redirect_url": b.get("redirect_url")}


def enregistrer_cle_banque(pem):
    banque.charger_cle(pem)                      # vérifie que la clé est lisible avant de l'enregistrer
    os.makedirs(DOSSIER, exist_ok=True)
    fd = os.open(CLE_BANQUE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(pem if isinstance(pem, str) else pem.decode())


def banque_connectee(d):
    b = d["banque"]
    return bool(b.get("session_id") and b.get("compte") and b.get("app_id") and os.path.exists(CLE_BANQUE))


def synchroniser(d):
    """Récupère les opérations du compte des loyers. Renvoie (nouvelles, deja)."""
    b = d["banque"]
    today = aujourdhui()
    if b.get("valide_jusqu") and b["valide_jusqu"] < today.isoformat():
        raise banque.ErreurBanque(f"L'autorisation donnée à la banque a expiré le {b['valide_jusqu']} : "
                                  "reconnecte la banque (bouton Banque)")
    if b.get("derniere_synchro"):
        depuis = dt.date.fromisoformat(b["derniere_synchro"][:10]) - dt.timedelta(days=10)
    else:
        depuis = today - dt.timedelta(days=90)
    ops = banque.operations(conf_banque(d), b["compte"], depuis.isoformat())
    r = ajouter_operations(d, ops, SOURCE_BANQUE)
    b["derniere_synchro"] = maintenant()
    return r


def prevenir_expiration(d):
    """Un e-mail au bailleur 10 jours avant la fin de l'autorisation bancaire (puis à l'expiration)."""
    b = d["banque"]
    fin = b.get("valide_jusqu")
    if not fin or not banque_connectee(d) or not d["bailleur"].get("email") or not envoi.configure(d["smtp"]):
        return
    reste = (dt.date.fromisoformat(fin) - aujourdhui()).days
    etape = "expiree" if reste < 0 else "bientot" if reste <= 10 else ""
    if not etape or b.get("alerte_expiration") == f"{fin}:{etape}":
        return
    texte = (f"L'accès de Suivi Loyers à ton compte bancaire {'a expiré' if reste < 0 else 'expire'} le "
             f"{qt.date_longue(fin)}.\n\nPour que les loyers continuent d'être vérifiés automatiquement, ouvre "
             "Suivi Loyers, clique sur « Banque » puis « Reconnecter » (deux minutes, avec ton application "
             "bancaire).\n\nLes banques imposent ce renouvellement tous les 180 jours au plus.\n")
    try:
        envoi.envoyer(d["smtp"], DOSSIER, d["bailleur"]["email"], "Suivi Loyers — accès bancaire à renouveler", texte)
        b["alerte_expiration"] = f"{fin}:{etape}"
        noter(d, "Rappel envoyé : accès bancaire à renouveler")
    except Exception as ex:
        noter(d, f"Rappel de renouvellement non envoyé : {ex}")


def ajouter_paiement_manuel(d, bail_id, date, montant, note=""):
    bail = trouver_bail(d, int(bail_id))
    ident = "m:" + hashlib.sha1(f"{bail_id}|{date}|{montant}|{maintenant()}|{len(d['operations'])}".encode()).hexdigest()[:16]
    d["operations"].append({"id": ident, "date": releves.date_iso(date), "montant": int(montant),
                            "libelle": note or "Paiement saisi à la main", "source": "manuel",
                            "bail": bail["id"], "methode": "manuel", "importee_le": maintenant()})
    d["operations"].sort(key=lambda o: o["date"])


def scanner(fichiers=(), envoyer=True, boite=True):
    """Import + rapprochement + quittances. Utilisé par la CLI, la planification et l'interface."""
    d = charger()
    rapport = {"fichiers": [], "affectees": 0, "a_verifier": 0, "banque": None}
    if banque_connectee(d):
        try:
            n, deja = synchroniser(d)
            rapport["banque"] = f"{n} nouvelle(s) opération(s)"
            d["banque"].pop("erreur", None)
        except Exception as ex:
            rapport["banque"] = f"ERREUR {ex}"
            d["banque"]["erreur"] = str(ex)[:300]
            noter(d, f"Synchronisation bancaire impossible : {ex}")
        prevenir_expiration(d)
    a_traiter = [(f, False) for f in fichiers]
    if boite:
        os.makedirs(BOITE, exist_ok=True)
        a_traiter += [(os.path.join(BOITE, f), True) for f in sorted(os.listdir(BOITE))
                      if not f.startswith(".") and os.path.isfile(os.path.join(BOITE, f))]
    for chemin, ranger in a_traiter:
        try:
            with open(chemin, "rb") as f:
                n, deja = importer(d, f.read(), chemin)
            rapport["fichiers"].append(f"{os.path.basename(chemin)} : {n} nouvelle(s), {deja} déjà connue(s)")
            if ranger:
                os.makedirs(RANGES, exist_ok=True)
                cible = os.path.join(RANGES, dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + os.path.basename(chemin))
                shutil.move(chemin, cible)
        except Exception as ex:
            rapport["fichiers"].append(f"{os.path.basename(chemin)} : ERREUR {ex}")
            noter(d, f"Import impossible de {os.path.basename(chemin)} : {ex}")
    rapport["affectees"] = len(rapprocher(d))
    rapport["a_verifier"] = sum(1 for o in d["operations"] if o["montant"] > 0 and not o.get("bail")
                                and not o.get("ignoree") and not o.get("manuel_libre"))
    rapport.update(emettre(d, envoyer))
    d["dernier_scan"] = maintenant()
    sauver(d)
    return rapport


# --------------------------------------------------------------------------- CLI

def statut(periode=None):
    d = charger()
    periode = periode or mois(aujourdhui().isoformat())
    print(f"Loyers de {qt.libelle_periode(periode)}")
    for b in d["baux"]:
        if not b.get("actif", True) or not actif_a(b, periode) or b["debut"] > periode:
            continue
        e = situation(d, b)[0].get(periode)
        if not e:
            continue
        q = trouver_quittance(d, b["id"], periode)
        envoi_txt = (" — quittance envoyée" if q and q["envoyee_le"] else " — quittance prête" if q else "")
        print(f"  {b['locataire'][:28]:<28} {qt.euros(e['paye']):>12} / {qt.euros(e['du']):<12} {e['statut']}{envoi_txt}")


def main(args):
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args[0] == "scan":
        fichiers = [a for a in args[1:] if not a.startswith("--")]
        r = scanner(fichiers, envoyer="--sans-envoi" not in args)
        if r["banque"]:
            print("Banque  ", r["banque"])
        for f in r["fichiers"]:
            print("Import  ", f)
        print(f"Paiements reconnus : {r['affectees']}   À vérifier : {r['a_verifier']}")
        for x in r["generees"]:
            print("Quittance générée :", x)
        for x in r["envoyees"]:
            print("Quittance envoyée :", x)
        for x in r["erreurs"]:
            print("ERREUR d'envoi :", x)
        statut()
        return 1 if r["erreurs"] or (r["banque"] or "").startswith("ERREUR") else 0
    if args[0] == "statut":
        statut(args[1] if len(args) > 1 else None)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
