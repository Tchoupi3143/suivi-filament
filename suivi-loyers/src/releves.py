# SPDX-License-Identifier: GPL-3.0-or-later
"""
Lecture des relevés bancaires exportés depuis l'espace client de la banque.

Formats acceptés (détection automatique) :
  - OFX / QFX (« Money », « Quicken », proposé par presque toutes les banques françaises)
  - QIF (« Quicken »)
  - CAMT.053 (XML ISO 20022, banques pro / Qonto / Shine…)
  - CSV (séparateur ; , ou tabulation, montants « 1 234,56 », colonnes Débit/Crédit ou Montant)

Chaque opération est rendue sous la forme :
  {"date": "AAAA-MM-JJ", "montant": centimes (int, > 0 = crédit), "libelle": str, "ref": str|None}
"""
import csv
import datetime as dt
import io
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation


class FormatInconnu(ValueError):
    pass


def decoder(octets):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return octets.decode(enc)
        except UnicodeDecodeError:
            continue
    return octets.decode("utf-8", errors="replace")


def centimes(texte):
    """« 1 234,56 », « -1234.56 », « 1.234,56 € », « +850 » -> centimes (int)."""
    s = str(texte or "").strip().replace("\xa0", "").replace(" ", "").replace(" ", "")
    s = s.replace("€", "").replace("EUR", "").strip()
    if not s:
        raise ValueError("montant vide")
    negatif = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("+-()")
    if "," in s and "." in s:                       # le dernier séparateur est le décimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = int((Decimal(s) * 100).quantize(Decimal("1")))
    except InvalidOperation:
        raise ValueError(f"montant illisible : {texte!r}")
    return -v if negatif else v


def date_iso(texte):
    s = str(texte or "").strip()[:10]
    for f in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%Y%m%d"):
        try:
            return dt.datetime.strptime(s if f != "%Y%m%d" else s[:8], f).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"date illisible : {texte!r}")


# --------------------------------------------------------------------------- OFX

def lire_ofx(texte):
    ops = []
    for bloc in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", texte, re.S | re.I):
        def champ(nom):
            m = re.search(r"<" + nom + r">([^<\r\n]*)", bloc, re.I)
            return m.group(1).strip() if m else ""
        libelle = " ".join(x for x in (champ("NAME"), champ("MEMO")) if x)
        ops.append({"date": date_iso(champ("DTPOSTED")[:8]), "montant": centimes(champ("TRNAMT")),
                    "libelle": libelle, "ref": champ("FITID") or None})
    return ops


# --------------------------------------------------------------------------- QIF

def date_qif(s):
    s = s.strip().replace("'", "/").replace(" ", "")
    try:
        return date_iso(s)
    except ValueError:
        j, m, a = re.split(r"[/.-]", s)
        a = int(a)
        return date_iso(f"{int(j):02d}/{int(m):02d}/{a + 2000 if a < 100 else a}")


def lire_qif(texte):
    ops, cour = [], {}
    for ligne in texte.splitlines():
        if not ligne.strip() or ligne.startswith("!"):
            continue
        code, val = ligne[0], ligne[1:].strip()
        if code == "^":
            if "D" in cour and "T" in cour:
                ops.append({"date": date_qif(cour["D"]), "montant": centimes(cour["T"]),
                            "libelle": " ".join(x for x in (cour.get("P"), cour.get("M")) if x),
                            "ref": cour.get("N") or None})
            cour = {}
        elif code in "DTPMN" and code not in cour:
            cour[code] = val
        elif code == "U" and "T" not in cour:
            cour["T"] = val
    return ops


# --------------------------------------------------------------------------- CAMT.053

def lire_camt(texte):
    racine = ET.fromstring(texte.encode("utf-8"))
    ns = racine.tag.split("}")[0] + "}" if racine.tag.startswith("{") else ""

    def tous(el, chemin):
        return el.findall(".//" + "/".join(ns + p for p in chemin.split("/")))

    def un(el, chemin):
        r = tous(el, chemin)
        return (r[0].text or "").strip() if r else ""

    ops = []
    for e in tous(racine, "Ntry"):
        montant = centimes(un(e, "Amt"))
        if un(e, "CdtDbtInd") == "DBIT":
            montant = -montant
        date = un(e, "BookgDt/Dt") or un(e, "BookgDt/DtTm") or un(e, "ValDt/Dt")
        morceaux = [un(e, "RltdPties/Dbtr/Nm") or un(e, "RltdPties/Dbtr/Pty/Nm"),
                    " ".join((x.text or "").strip() for x in tous(e, "RmtInf/Ustrd")),
                    un(e, "AddtlNtryInf")]
        ops.append({"date": date_iso(date), "montant": montant,
                    "libelle": " ".join(m for m in morceaux if m),
                    "ref": un(e, "AcctSvcrRef") or un(e, "NtryRef") or None})
    return ops


# --------------------------------------------------------------------------- CSV

def _norm(s):
    s = s.lower().strip()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("ô", "o"), ("û", "u"), ("à", "a")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


COL_DATE = ("date operation", "date", "date comptable", "date de l operation", "booking date", "date valeur")
COL_LIB = ("libelle", "libelle operation", "libelle simplifie", "description", "label", "intitule",
           "detail", "details", "operation", "nature de l operation", "communication", "contrepartie",
           "informations complementaires", "info complementaire", "motif", "beneficiaire", "tiers")
COL_MONTANT = ("montant", "montant eur", "montant euros", "montant en euros", "amount", "valeur")
COL_CREDIT = ("credit", "credit eur", "credit euros", "credits", "montant credit", "recette")
COL_DEBIT = ("debit", "debit eur", "debit euros", "debits", "montant debit", "depense")


def _trouver(entetes, noms, deja=()):
    for nom in noms:                       # correspondance exacte d'abord
        for i, h in enumerate(entetes):
            if h == nom and i not in deja:
                return i
    for nom in noms:
        for i, h in enumerate(entetes):
            if i not in deja and h.startswith(nom):
                return i
    return None


def lire_csv(texte):
    lignes = texte.splitlines()
    echantillon = "\n".join(lignes[:30])
    sep = max((";", ",", "\t", "|"), key=lambda c: echantillon.count(c))
    rangs = list(csv.reader(io.StringIO(texte), delimiter=sep))
    # l'en-tête est la première ligne qui contient une colonne « date » et une colonne de montant
    for n, r in enumerate(rangs[:40]):
        h = [_norm(c) for c in r]
        idate = _trouver(h, COL_DATE)
        if idate is None:
            continue
        imontant = _trouver(h, COL_MONTANT)
        icredit, idebit = _trouver(h, COL_CREDIT), _trouver(h, COL_DEBIT)
        if imontant is None and icredit is None:
            continue
        exclus = {i for i in (idate, imontant, icredit, idebit) if i is not None}
        ilib = [i for i in range(len(h)) if i not in exclus and any(h[i].startswith(x) for x in COL_LIB)]
        break
    else:
        apercu = " | ".join(rangs[0][:8]) if rangs else ""
        raise FormatInconnu("CSV : impossible de trouver les colonnes Date / Libellé / Montant"
                            + (f" (première ligne : {apercu[:200]})" if apercu else ""))
    ops = []
    for r in rangs[n + 1:]:
        if len(r) <= idate or not r[idate].strip():
            continue
        try:
            date = date_iso(r[idate])
        except ValueError:
            continue                      # ligne de total, solde, etc.
        try:
            if imontant is not None and r[imontant].strip():
                montant = centimes(r[imontant])
            else:
                cr = r[icredit].strip() if icredit is not None and len(r) > icredit else ""
                db = r[idebit].strip() if idebit is not None and len(r) > idebit else ""
                montant = abs(centimes(cr)) if cr else -abs(centimes(db)) if db else None
        except ValueError:
            continue
        if not montant:
            continue
        libelle = " ".join(r[i].strip() for i in ilib if i < len(r) and r[i].strip())
        ops.append({"date": date, "montant": montant, "libelle": re.sub(r"\s+", " ", libelle), "ref": None})
    return ops


# --------------------------------------------------------------------------- point d'entrée

def lire(octets, nom=""):
    texte = decoder(octets)
    debut = texte.lstrip()[:400].upper()
    if "<OFX>" in texte.upper() or "OFXHEADER" in debut:
        ops = lire_ofx(texte)
    elif debut.startswith("!TYPE") or debut.startswith("!ACCOUNT") or debut.startswith("!OPTION"):
        ops = lire_qif(texte)
    elif debut.startswith("<?XML") or debut.startswith("<DOCUMENT"):
        if "CAMT.05" not in texte[:2000].lower() and "BkToCstmrStmt" not in texte:
            raise FormatInconnu("XML non reconnu (seul le CAMT.053 est accepté)")
        ops = lire_camt(texte)
    else:
        ops = lire_csv(texte)
    if not ops:
        raise FormatInconnu(f"{nom or 'fichier'} : aucune opération trouvée")
    return ops
