# SPDX-License-Identifier: GPL-3.0-or-later
"""
Quittance de loyer (et reçu de paiement partiel) au format PDF.

Contenu conforme à l'article 21 de la loi n° 89-462 du 6 juillet 1989 : quittance
gratuite, détail du loyer et des charges ; en cas de paiement partiel, simple reçu.
Petit générateur PDF intégré (polices standard Helvetica) : aucune dépendance.
"""
import calendar
import datetime as dt

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

# largeurs Helvetica (1/1000 em), caractères 32 à 126
_L = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278] + [556] * 10 + \
     [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
      722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
      556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556,
      500, 722, 500, 500, 500, 334, 260, 334, 584]
_BASE = str.maketrans("àâäéèêëîïôöùûüçÀÂÉÈÊËÎÏÔÙÛÇ€", "aaaeeeeiioouuucAAEEEEIIOUUCo")


def largeur(texte, taille, gras=False):
    t = texte.translate(_BASE)
    w = sum(_L[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in t)
    return w * taille / 1000 * (1.1 if gras else 1)


def euros(c):
    s = f"{abs(c) // 100:,}".replace(",", " ") + f",{abs(c) % 100:02d} €"
    return ("-" if c < 0 else "") + s


# --------------------------------------------------------------------------- montant en lettres

_U = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
      "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
_D = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


def _cent(n):
    """0 < n < 1000 (orthographe rectifiée de 1990 : traits d'union partout)."""
    c, r = divmod(n, 100)
    mots = []
    if c:
        mots.append("cent" if c == 1 else _U[c] + "-cents" if r == 0 else _U[c] + "-cent")
    if r:
        if r < 20:
            mots.append(_U[r])
        else:
            d, u = divmod(r, 10)
            if d in (7, 9):
                base, u = ("soixante" if d == 7 else "quatre-vingt"), u + 10
                mots.append(base + ("-et-" if (d == 7 and u == 11) else "-") + _U[u])
            elif d == 8:
                mots.append("quatre-vingts" if u == 0 else "quatre-vingt-" + _U[u])
            else:
                mots.append(_D[d] + ("" if u == 0 else "-et-un" if u == 1 else "-" + _U[u]))
    return "-".join(mots)


def en_lettres(n):
    if n == 0:
        return "zéro"
    morceaux = []
    for valeur, nom in ((10 ** 9, "milliard"), (10 ** 6, "million"), (1000, "mille")):
        q, n = divmod(n, valeur)
        if q:
            if nom == "mille":
                morceaux.append("mille" if q == 1 else _cent(q).replace("-cents", "-cent").replace("vingts", "vingt")
                                + "-mille")
            else:
                morceaux.append(_cent(q) + "-" + nom + ("s" if q > 1 else ""))
    if n:
        morceaux.append(_cent(n))
    return "-".join(morceaux)


def montant_en_lettres(c):
    e, ct = divmod(c, 100)
    s = en_lettres(e) + (" euro" if e <= 1 else " euros")
    if e >= 10 ** 6 and e % 10 ** 6 == 0:
        s = s.replace(" euros", " d'euros")
    if ct:
        s += " et " + en_lettres(ct) + (" centime" if ct == 1 else " centimes")
    return s


# --------------------------------------------------------------------------- mini-PDF

class Page:
    def __init__(self):
        self.ops = []

    @staticmethod
    def _txt(s):
        b = s.replace(" ", " ").replace(" ", " ").replace("’", "'").encode("cp1252", errors="replace")
        return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")

    def texte(self, x, y, s, taille=10, gras=False, align="g", gris=False):
        if align == "d":
            x -= largeur(s, taille, gras)
        elif align == "c":
            x -= largeur(s, taille, gras) / 2
        couleur = b"0.42 g " if gris else b"0 g "
        self.ops.append(couleur + b"BT /F%d %.1f Tf %.2f %.2f Td (" % (2 if gras else 1, taille, x, y)
                        + self._txt(s) + b") Tj ET")

    def paragraphe(self, x, y, s, l_max, taille=10, interligne=1.45, gras=False):
        mots, ligne = s.split(" "), ""
        for m in mots:
            essai = (ligne + " " + m).strip()
            if largeur(essai, taille, gras) > l_max and ligne:
                self.texte(x, y, ligne, taille, gras)
                y -= taille * interligne
                ligne = m
            else:
                ligne = essai
        if ligne:
            self.texte(x, y, ligne, taille, gras)
            y -= taille * interligne
        return y

    def trait(self, x1, y1, x2, y2, epaisseur=0.6, gris=0.75):
        self.ops.append(b"%.2f G %.2f w %.2f %.2f m %.2f %.2f l S" % (gris, epaisseur, x1, y1, x2, y2))

    def cadre(self, x, y, l, h, fond=0.96):
        self.ops.append(b"%.2f g %.2f %.2f %.2f %.2f re f" % (fond, x, y, l, h))

    def pdf(self, titre=""):
        flux = b"\n".join(self.ops)
        objets = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] "
            b"/Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
            b"<< /Length %d >>\nstream\n" % len(flux) + flux + b"\nendstream",
            b"<< /Title (" + self._txt(titre) + b") /Producer (Suivi Loyers) >>",
        ]
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        positions = []
        for i, o in enumerate(objets, 1):
            positions.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objets) + 1)
        for p in positions:
            out += b"%010d 00000 n \n" % p
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info 7 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objets) + 1, xref)
        return bytes(out)


# --------------------------------------------------------------------------- document

def date_longue(iso):
    d = dt.date.fromisoformat(iso)
    return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]} {d.year}"


def bornes(periode):
    a, m = map(int, periode.split("-"))
    return dt.date(a, m, 1).isoformat(), dt.date(a, m, calendar.monthrange(a, m)[1]).isoformat()


def libelle_periode(periode):
    a, m = map(int, periode.split("-"))
    return f"{MOIS[m - 1]} {a}"


def generer(bailleur, bail, periode, loyer, charges, paye, date_paiement, numero, emise_le=None, jours=None):
    """
    Renvoie le PDF (bytes). Si paye < loyer + charges : reçu de paiement partiel.
    Montants en centimes.
    """
    total = loyer + charges
    complet = paye >= total
    emise_le = emise_le or dt.date.today().isoformat()
    debut, fin = bornes(periode)
    if jours:                                   # entrée ou sortie en cours de mois : période réelle
        debut, fin = debut[:8] + f"{jours[0]:02d}", debut[:8] + f"{jours[1]:02d}"
    p = Page()
    G, D, L = 64, 531, 467                                   # marges gauche/droite, largeur utile
    titre = "Quittance de loyer" if complet else "Reçu de paiement partiel"

    p.texte(G, 778, titre.upper(), 20, gras=True)
    p.texte(G, 756, f"Période : {libelle_periode(periode)}  —  du {date_longue(debut)} au {date_longue(fin)}", 10.5)
    p.texte(D, 778, f"N° {numero}", 10, align="d", gris=True)
    p.trait(G, 740, D, 740)

    # blocs bailleur / locataire
    def bloc(x, y, entete, lignes):
        p.texte(x, y, entete.upper(), 8, gras=True, gris=True)
        y -= 16
        for i, l in enumerate(lignes):
            if l:
                p.texte(x, y, l, 10.5, gras=(i == 0))
                y -= 14
        return y

    adr_bailleur = [bailleur.get("nom", "")] + (bailleur.get("adresse") or "").splitlines()
    y1 = bloc(G, 715, "Bailleur", adr_bailleur)
    y2 = bloc(320, 715, "Locataire", [bail["locataire"]] + (bail.get("logement") or "").splitlines())
    y = min(y1, y2) - 12
    p.texte(G, y, "ADRESSE DU LOGEMENT LOUÉ", 8, gras=True, gris=True)
    y = p.paragraphe(G, y - 15, " — ".join((bail.get("logement") or "").splitlines()), L, 10.5)
    y -= 14

    # déclaration
    signataire = bailleur.get("signataire") or bailleur.get("nom", "")
    if complet:
        phrase = (f"Je soussigné(e) {signataire}, bailleur du logement désigné ci-dessus, déclare avoir reçu de "
                  f"{bail['locataire']} la somme de {euros(total)} ({montant_en_lettres(total)}), au titre du "
                  f"paiement du loyer et des charges pour la période de location du {date_longue(debut)} au "
                  f"{date_longue(fin)}, et lui en donne quittance, sous réserve de tous mes droits.")
    else:
        phrase = (f"Je soussigné(e) {signataire}, bailleur du logement désigné ci-dessus, déclare avoir reçu de "
                  f"{bail['locataire']} la somme de {euros(paye)} ({montant_en_lettres(paye)}), à titre de "
                  f"paiement partiel du loyer et des charges dus pour la période du {date_longue(debut)} au "
                  f"{date_longue(fin)}. Ce reçu ne vaut pas quittance.")
    y = p.paragraphe(G, y, phrase, L, 10.5, 1.5)
    y -= 18

    # détail
    lignes = [("Loyer hors charges", loyer), ("Provision pour charges", charges), ("Total dû pour la période", total)]
    if not complet:
        lignes += [("Montant reçu", paye), ("Reste à payer", total - paye)]
    h = 24 * len(lignes) + 30
    p.cadre(G, y - h + 14, L, h)
    p.texte(G + 14, y - 4, "DÉTAIL DU RÈGLEMENT", 8, gras=True, gris=True)
    y -= 28
    for i, (lib, m) in enumerate(lignes):
        fort = lib.startswith(("Total", "Reste"))
        if fort:
            p.trait(G + 14, y + 15, D - 14, y + 15, 0.5, 0.8)
        p.texte(G + 14, y, lib, 10.5, gras=fort)
        p.texte(D - 14, y, euros(m), 10.5, gras=fort, align="d")
        y -= 24
    y -= 16
    p.texte(G, y, f"Date du paiement : {date_longue(date_paiement)}", 10.5)
    y -= 34

    ville = bailleur.get("ville") or ""
    p.texte(G, y, (f"Fait à {ville}, le " if ville else "Fait le ") + date_longue(emise_le), 10.5)
    p.texte(D, y, "Le bailleur", 10.5, align="d", gris=True)
    p.texte(D, y - 30, signataire, 12, gras=True, align="d")

    p.trait(G, 92, D, 92)
    mentions = ("Cette quittance annule tous les reçus qui auraient pu être établis précédemment en cas de "
                "paiement partiel du montant du présent terme. " if complet else "") + \
               ("Document délivré gratuitement (art. 21 de la loi n° 89-462 du 6 juillet 1989). "
                "À conserver par le locataire.")
    p.paragraphe(G, 78, mentions, L, 8, 1.4)
    return p.pdf(f"{titre} {libelle_periode(periode)} - {bail['locataire']}")
