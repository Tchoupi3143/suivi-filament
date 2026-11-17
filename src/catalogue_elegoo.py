#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tchoupi3143 — Suivi Filament
"""
Catalogue des filaments Elegoo (boutique Europe, prix en euros).

Lit le catalogue public de la boutique (format Shopify products.json) et le
transforme en : gamme -> couleur -> formats d'achat, avec le prix au kg.

    python3 catalogue_elegoo.py [sortie.json]     # télécharge et construit
"""
import datetime as dt
import json
import re
import sys
import urllib.request

BOUTIQUE = "https://eu.elegoo.com"
COLLECTION = BOUTIQUE + "/collections/filaments/products.json?limit=250&page={}"

# --------------------------------------------------------------------------- couleurs
# Teinte approximative à partir du nom Elegoo (modifiable ensuite dans l'app).
TEINTES = [
    ("transparent", "#e6edf2"), ("translucent", "#dfe8ee"), ("clear", "#e6edf2"), ("crytal", "#eef3f6"),
    ("marble brick", "#a45a4a"), ("marble cement", "#9e9e9a"), ("marble", "#d9d9d4"),
    ("rilievo cyan", "#00a3e0"), ("rilievo magenta", "#d6007e"), ("rilievo yellow", "#ffe100"),
    ("rilievo white", "#f7f7f7"),
    ("neon green", "#39d353"), ("mint", "#8fe3c0"), ("olive", "#7a8a3a"), ("apple green", "#8bc34a"),
    ("sea green", "#2e8b57"), ("teal", "#00897b"), ("turquoise", "#1fb5a8"), ("holly green", "#2f6b3a"),
    ("sky blue", "#64b5f6"), ("light blue", "#90caf9"), ("ice blue", "#b3e5fc"), ("misty blue", "#8fa9c7"),
    ("dark blue", "#1a3a8f"), ("navy", "#1b2a5b"), ("cobalt", "#1f4fbf"), ("peacock", "#126e82"),
    ("lavender", "#b39ddb"), ("light purple", "#c5a3e0"),
    ("hot pink", "#ff2d95"), ("sakura", "#f8bbd0"), ("light pink", "#f8c8d8"), ("peach", "#ffb08a"),
    ("coral", "#ff7f6e"),
    ("burgundy", "#7b1e2b"), ("ruby", "#9b111e"), ("rose red", "#c2185b"), ("brick", "#a45a4a"),
    ("rosewood", "#65000b"), ("true red", "#d01c1f"),
    ("orange yellow", "#ffb300"), ("sunflower", "#ffc107"), ("sunshine", "#ffd54f"),
    ("cocoa", "#5d3a2a"), ("walnut", "#5d4037"), ("earth brown", "#6b4f3a"), ("medium brown", "#8d6e63"),
    ("light brown", "#b08968"), ("oak", "#c19a6b"), ("tan", "#d2b48c"), ("birch", "#e3cfa8"),
    ("wood", "#a1764a"), ("beige", "#e2d3b5"), ("sand", "#c2b280"),
    ("space grey", "#4a4a4f"), ("slate", "#5b6770"), ("dark grey", "#4a4a4f"), ("light grey", "#c7c7cc"),
    ("silver", "#c0c0c0"), ("copper", "#b87333"), ("bronze", "#8c6239"), ("gold", "#c9a227"),
    ("black", "#1d1d1f"), ("white", "#f4f4f4"), ("grey", "#8e8e93"), ("gray", "#8e8e93"),
    ("red", "#d32f2f"), ("orange", "#f57c00"), ("yellow", "#fbc02d"), ("green", "#2e7d32"),
    ("cyan", "#00bcd4"), ("blue", "#1e63c9"), ("purple", "#7b1fa2"), ("magenta", "#d6007e"),
    ("pink", "#f06292"), ("brown", "#6d4c41"), ("amber", "#ffbf00"),
]


TYPES = {"filament with spool": "PLA Basic", "refill": "PLA Basic Refill"}


def teinte(nom):
    n = nom.lower()
    for mot, hexa in TEINTES:
        if mot in n:
            return hexa
    return "#888888"


# --------------------------------------------------------------------------- noms

def propre(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def cle(s):
    """Clé de rapprochement entre une gamme à l'unité et ses lots."""
    s = propre(s).lower().replace("®", "")
    s = re.sub(r"\bplus\b", "+", s).replace(" +", "+")
    s = re.sub(r"\b(filament|filaments|spool|1\.75 ?mm|colored|1 ?kg)\b", " ", s)
    s = re.sub(r"\b\d+(\.\d+)? ?kg\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def matiere(nom):
    n = nom.upper()
    for m in ("PETG", "PET", "PLA", "ABS", "ASA", "TPU", "PAHT", "PA", "PC", "PPS"):
        if re.search(r"(^|[^A-Z])" + m + r"([^A-Z]|$)", n):
            return {"PAHT": "PA"}.get(m, m)
    return "Autre"


def kg_dans(texte):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*kg", texte.lower())
    return float(m.group(1).replace(",", ".")) if m else None


def option(p, v, mot):
    for i, o in enumerate(p["options"], start=1):
        if mot in o["name"].lower():
            return propre(v.get(f"option{i}"))
    return None


# --------------------------------------------------------------------------- construction

def construire(produits):
    gammes, lots = {}, []
    for p in produits:
        titre = propre(p["title"])
        if "bundle" in titre.lower() or "250 g" in titre.lower():
            continue                                   # assortiments multicolores : ignorés
        kg_titre = kg_dans(titre)
        for v in p["variants"]:
            couleur = option(p, v, "color") or (propre(v["title"]) if v["title"] != "Default Title" else None)
            couleur = re.sub(r"\s*/\s*\d+(\.\d+)?\s*kg$", "", couleur) if couleur else None
            typ = option(p, v, "type")
            prix = float(v["price"])
            if kg_titre:                                # lot (10 × 1 kg) ou grosse bobine (3 / 5 kg)
                base = TYPES.get(typ.lower(), typ) if typ else titre
                grosse = "spool" in titre.lower()
                lots.append({"cle": cle(base), "base": base, "couleur": (couleur or "").lower(), "prix": prix, "kg": kg_titre,
                             "bobine_kg": kg_titre if grosse else 1.0,
                             "libelle": f"Bobine {fmt(kg_titre)} kg" if grosse else f"Lot {fmt(kg_titre)} kg",
                             "dispo": v["available"]})
                continue
            couleur = couleur or "Unique"
            nom = TYPES.get(typ.lower(), typ) if typ else titre
            kg_v = kg_dans(v["title"]) or 1.0
            g = gammes.setdefault(nom, {"id": re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-"),
                                        "nom": nom, "matiere": matiere(nom), "url": f"{BOUTIQUE}/products/{p['handle']}",
                                        "couleurs": {}})
            c = g["couleurs"].setdefault(couleur, {"nom": couleur, "hex": teinte(couleur), "dispo": False, "formats": []})
            c["dispo"] = c["dispo"] or v["available"]
            c["formats"].append({"libelle": f"Bobine {fmt(kg_v)} kg", "prix": prix, "kg": kg_v,
                                 "bobine_kg": kg_v, "prix_kg": round(prix / kg_v, 2), "dispo": v["available"]})

    # rattacher lots et grosses bobines aux gammes
    index = {}
    for g in gammes.values():
        index.setdefault(cle(g["nom"]), g)
    orphelins = 0
    for l in lots:
        g = index.get(l["cle"])
        if not g and not l["couleur"] and " " in l["cle"]:
            # ex. « PLA (RFID) Filament Grey 10 kg » : la couleur est dans le titre
            base, mot = l["cle"].rsplit(" ", 1)
            g, l["couleur"] = index.get(base), mot
        if g and not l["couleur"] and len(g["couleurs"]) == 1:
            l["couleur"] = next(iter(g["couleurs"])).lower()     # produit à couleur unique
        if (not g or g.get("_lots")) and l["libelle"].startswith("Bobine") and l["couleur"]:
            # grosse bobine sans équivalent à l'unité (ex. PETG 3 kg) : gamme à part
            nom = propre(l["base"])
            g = gammes.setdefault(nom, {"id": re.sub(r"[^a-z0-9]+", "-", nom.lower()).strip("-"), "nom": nom,
                                        "matiere": matiere(nom), "url": BOUTIQUE + "/collections/filaments",
                                        "couleurs": {}, "_lots": True})
            index[l["cle"]] = g
            nc = l["couleur"].title()
            if not any(n.lower() == l["couleur"] for n in g["couleurs"]):
                g["couleurs"][nc] = {"nom": nc, "hex": teinte(nc), "dispo": False, "formats": []}
        c = g and next((c for n, c in g["couleurs"].items() if n.lower() == l["couleur"]), None)
        if not c:
            orphelins += 1
            continue
        c["dispo"] = c["dispo"] or l["dispo"]
        if any(f["libelle"] == l["libelle"] for f in c["formats"]):
            continue
        c["formats"].append({"libelle": l["libelle"], "prix": l["prix"], "kg": l["kg"], "bobine_kg": l["bobine_kg"],
                             "prix_kg": round(l["prix"] / l["kg"], 2), "dispo": l["dispo"]})

    sortie = []
    for g in sorted(gammes.values(), key=lambda g: (ordre(g["matiere"]), g["nom"].lower())):
        coul = sorted(g["couleurs"].values(), key=lambda c: (not c["dispo"], c["nom"]))
        for c in coul:
            c["formats"].sort(key=lambda f: (f["kg"], f["prix"]))
        sortie.append({**{k: v for k, v in g.items() if not k.startswith("_")}, "couleurs": coul})
    return {"source": BOUTIQUE, "devise": "EUR", "maj": dt.date.today().isoformat(),
            "gammes": sortie, "lots_non_rattaches": orphelins}


def ordre(m):
    return ["PLA", "PETG", "PET", "ABS", "ASA", "TPU", "PC", "PA", "PPS"].index(m) if m in \
        ["PLA", "PETG", "PET", "ABS", "ASA", "TPU", "PC", "PA", "PPS"] else 99


def fmt(x):
    return f"{x:g}".replace(".", ",")


def telecharger(timeout=20):
    produits, page = [], 1
    while page <= 10:
        req = urllib.request.Request(COLLECTION.format(page), headers={"User-Agent": "SuiviFilament/1.0",
                                                                        "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            lot = json.load(r).get("products", [])
        if not lot:
            break
        produits += lot
        page += 1
    if not produits:
        raise RuntimeError("catalogue vide")
    return construire(produits)


if __name__ == "__main__":
    if len(sys.argv) > 2:                       # construire depuis un fichier products.json déjà téléchargé
        cat = construire(json.load(open(sys.argv[2], encoding="utf-8"))["products"])
    else:
        cat = telecharger()
    out = sys.argv[1] if len(sys.argv) > 1 else "catalogue_elegoo.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, indent=1)
    print(f"{len(cat['gammes'])} gammes, {sum(len(g['couleurs']) for g in cat['gammes'])} couleurs, "
          f"{cat['lots_non_rattaches']} lots non rattachés -> {out}")
