#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tchoupi3143 — Suivi Filament
"""
Suivi de filament pour ElegooSlicer / OrcaSlicer / Bambu Studio.

Deux usages avec le même fichier :

1) Script de post-traitement (appelé automatiquement par le slicer) :
       python suivi_filament.py <fichier.gcode>
   -> lit la consommation (g) dans le G-code, la retire du stock de la bobine
      active de chaque emplacement, l'inscrit dans l'historique et affiche une
      alerte si une bobine n'a pas assez de filament pour l'impression.

2) Gestion des bobines en ligne de commande :
       python suivi_filament.py ajouter --nom "PLA Noir Elegoo" --poids 1000
       python suivi_filament.py liste
       python suivi_filament.py activer 2 --emplacement 1
       python suivi_filament.py peser 2 --brut 612 --tare 180
       python suivi_filament.py corriger 2 --reste 430
       python suivi_filament.py annuler
       python suivi_filament.py historique
       python suivi_filament.py supprimer 3
       python suivi_filament.py seuil 100

Aucune dépendance : bibliothèque standard Python 3.8+ uniquement.
Les données sont dans bobines.json, à côté du script (ou dans le fichier
indiqué par la variable d'environnement SUIVI_FILAMENT_DATA).
"""

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys
import tempfile

MARQUEUR = "; suivi_filament:"
DATA = os.environ.get("SUIVI_FILAMENT_DATA") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "bobines.json")
HISTO_MAX = 500

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# --------------------------------------------------------------------------- données

def charger():
    if not os.path.exists(DATA):
        return {"bobines": [], "actives": {}, "historique": [], "seuil_alerte_g": 100, "prochain_id": 1}
    with open(DATA, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("bobines", []); d.setdefault("actives", {}); d.setdefault("historique", [])
    d.setdefault("seuil_alerte_g", 100)
    d.setdefault("prochain_id", max([b["id"] for b in d["bobines"]] + [0]) + 1)
    return d


def sauver(d):
    d["historique"] = d["historique"][-HISTO_MAX:]
    dossier = os.path.dirname(os.path.abspath(DATA))
    fd, tmp = tempfile.mkstemp(dir=dossier, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA)  # écriture atomique : pas de fichier corrompu en cas de coupure


def bobine(d, ident):
    for b in d["bobines"]:
        if b["id"] == ident:
            return b
    sys.exit(f"Bobine {ident} introuvable (voir : liste).")


def maintenant():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- lecture G-code

def _liste(val):
    out = []
    for x in re.split(r"[,;]", val):
        x = x.strip().strip('"')
        try:
            out.append(float(x))
        except ValueError:
            out.append(None)
    return out


def lire_gcode(chemin):
    """Retourne (grammes par emplacement, infos) depuis les commentaires du slicer."""
    with open(chemin, encoding="utf-8", errors="replace") as f:
        texte = f.read()

    def cherche(motif):
        m = re.search(motif, texte, re.M)
        return m.group(1).strip() if m else None

    infos = {
        "deja_traite": MARQUEUR in texte,
        "empreinte": hashlib.sha1(texte.encode("utf-8", "replace")).hexdigest(),
        "matiere": cherche(r"^;\s*filament_type\s*=\s*(.+)$"),
        "profil": cherche(r"^;\s*filament_settings_id\s*=\s*(.+)$"),
        "temps": cherche(r"^;\s*(?:estimated printing time \(normal mode\)|model printing time)\s*[=:]\s*(.+?)(?:;|$)"),
    }

    # 1) grammes par filament (OrcaSlicer / ElegooSlicer / Bambu / PrusaSlicer)
    g = cherche(r"^;\s*filament used \[g\]\s*=\s*(.+)$")
    grammes = _liste(g) if g else []
    # 2) sinon total en grammes (en-tête Orca)
    if not any(grammes):
        t = cherche(r"^;\s*total filament (?:weight|used) \[g\]\s*[:=]\s*(.+)$")
        grammes = _liste(t)[:1] if t else []
    # 3) sinon calcul depuis la longueur, la densité et le diamètre
    if not any(grammes):
        mm = cherche(r"^;\s*filament used \[mm\]\s*=\s*(.+)$")
        dens = cherche(r"^;\s*filament_density\s*=\s*(.+)$")
        diam = cherche(r"^;\s*filament_diameter\s*=\s*(.+)$")
        if mm:
            L = _liste(mm)
            D = _liste(dens) if dens else [1.24]
            DI = _liste(diam) if diam else [1.75]
            grammes = []
            for i, l in enumerate(L):
                if l is None:
                    grammes.append(None); continue
                rho = (D[i] if i < len(D) and D[i] else D[0]) or 1.24
                d_ = (DI[i] if i < len(DI) and DI[i] else DI[0]) or 1.75
                grammes.append(l * math.pi * (d_ / 2) ** 2 / 1000 * rho)
    grammes = [round(x, 2) if x else 0.0 for x in grammes]
    return grammes, infos, texte


def marquer_gcode(chemin, texte, lignes):
    """Ajoute un résumé en commentaire en tête du G-code (sans toucher aux commandes)."""
    entete = "".join(f"{MARQUEUR} {l}\n" for l in lignes)
    with open(chemin, "w", encoding="utf-8", newline="") as f:
        f.write(entete + texte)


# --------------------------------------------------------------------------- alertes

def alerte(titre, message):
    """Fenêtre d'alerte si possible (macOS / Windows / Linux avec écran), sinon console."""
    print(f"[{titre}] {message}", file=sys.stderr)
    if os.environ.get("SUIVI_FILAMENT_SANS_FENETRE"):
        return
    if sys.platform == "darwin":
        # macOS : alerte native via AppleScript (le Tk fourni par Apple est obsolète).
        # Le texte passe en argument, donc aucun souci d'apostrophes ou de guillemets.
        import subprocess
        try:
            subprocess.run(["osascript",
                            "-e", "on run argv",
                            "-e", "activate",
                            "-e", "display alert (item 1 of argv) message (item 2 of argv) as warning",
                            "-e", "end run", titre, message],
                           timeout=600, capture_output=True)
        except Exception:
            pass
        return
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk(); root.withdraw(); root.attributes("-topmost", True)
        messagebox.showwarning(titre, message, parent=root)
        root.destroy()
    except Exception:
        pass


# --------------------------------------------------------------------------- post-traitement

def post_traitement(chemin):
    d = charger()
    grammes, infos, texte = lire_gcode(chemin)
    nom_tache = os.path.basename(os.environ.get("SLIC3R_PP_OUTPUT_NAME") or chemin)
    if nom_tache.lower().endswith(".pp"):
        nom_tache = nom_tache[:-3]                    # copie temporaire du slicer

    if not any(grammes):
        journal("  aucune consommation trouvée dans le fichier (pas de ligne « filament used [g] »)")
        print("suivi_filament : aucune consommation trouvée dans le G-code, rien à faire.")
        return
    if infos["deja_traite"] or any(h.get("empreinte") == infos["empreinte"] for h in d["historique"][-50:]):
        journal("  déjà comptabilisé, ignoré")
        print("suivi_filament : ce G-code a déjà été comptabilisé, ignoré.")
        return

    resume, avertissements, deductions = [], [], []
    for i, g in enumerate(grammes, start=1):
        if g <= 0:
            continue
        ident = d["actives"].get(str(i))
        if ident is None:
            avertissements.append(f"Emplacement {i} : {g:.1f} g utilisés, mais aucune bobine active "
                                  f"(commande : activer <id> --emplacement {i}).")
            resume.append(f"emplacement {i} : {g:.1f} g (aucune bobine active)")
            continue
        b = bobine(d, ident)
        avant = b["reste_g"]
        b["reste_g"] = round(avant - g, 2)
        deductions.append({"bobine": ident, "g": g})
        resume.append(f"emplacement {i} : {g:.1f} g sur #{ident} {b['nom']} -> reste {b['reste_g']:.0f} g")
        if avant < g:
            avertissements.append(f"PAS ASSEZ de filament sur #{ident} {b['nom']} : l'impression demande "
                                  f"{g:.0f} g, il en reste {avant:.0f} g. Change de bobine avant de lancer !")
        elif b["reste_g"] < d["seuil_alerte_g"]:
            avertissements.append(f"Bobine #{ident} {b['nom']} presque vide : il restera {b['reste_g']:.0f} g "
                                  f"après cette impression.")

    d["historique"].append({
        "date": maintenant(), "tache": nom_tache, "deductions": deductions,
        "total_g": round(sum(grammes), 2), "temps": infos["temps"], "empreinte": infos["empreinte"],
    })
    sauver(d)

    try:
        marquer_gcode(chemin, texte, [maintenant()] + resume)
    except OSError:
        pass  # le G-code reste valide même si on ne peut pas l'annoter

    journal("  " + " | ".join(resume))
    print("suivi_filament : " + " | ".join(resume))
    if avertissements:
        alerte("Suivi filament", "\n\n".join(avertissements))


# --------------------------------------------------------------------------- commandes

def cmd_ajouter(a):
    d = charger()
    b = {"id": d["prochain_id"], "nom": a.nom, "matiere": a.matiere, "couleur": a.couleur,
         "poids_net_g": a.poids, "reste_g": a.reste if a.reste is not None else a.poids,
         "tare_g": a.tare, "prix_kg": a.prix, "ajoutee_le": maintenant()}
    d["bobines"].append(b); d["prochain_id"] += 1
    if a.emplacement:
        d["actives"][str(a.emplacement)] = b["id"]
    sauver(d)
    print(f"Bobine #{b['id']} ajoutée : {b['nom']} ({b['reste_g']:.0f} g)"
          + (f", active sur l'emplacement {a.emplacement}" if a.emplacement else ""))


def cmd_liste(a):
    d = charger()
    if not d["bobines"]:
        print("Aucune bobine. Ajoute-en une : ajouter --nom \"PLA Noir\" --poids 1000 --emplacement 1"); return
    actives = {v: k for k, v in d["actives"].items()}
    print(f"{'ID':>3}  {'Emp.':>4}  {'Nom':<28} {'Mat.':<6} {'Reste':>8}  {'%':>4}  {'Valeur':>7}")
    for b in d["bobines"]:
        pct = 100 * b["reste_g"] / b["poids_net_g"] if b["poids_net_g"] else 0
        val = f"{b['reste_g'] / 1000 * b['prix_kg']:.2f}€" if b.get("prix_kg") else ""
        emp = actives.get(b["id"], "")
        flag = "  ⚠" if b["reste_g"] < d["seuil_alerte_g"] else ""
        print(f"{b['id']:>3}  {emp:>4}  {b['nom'][:28]:<28} {(b.get('matiere') or '')[:6]:<6} "
              f"{b['reste_g']:>6.0f} g  {pct:>3.0f}%  {val:>7}{flag}")
    print(f"\nSeuil d'alerte : {d['seuil_alerte_g']} g   —   données : {DATA}")


def cmd_activer(a):
    d = charger(); b = bobine(d, a.id)
    d["actives"][str(a.emplacement)] = b["id"]; sauver(d)
    print(f"Emplacement {a.emplacement} -> bobine #{b['id']} {b['nom']}")


def cmd_peser(a):
    d = charger(); b = bobine(d, a.id)
    tare = a.tare if a.tare is not None else b.get("tare_g")
    if tare is None:
        sys.exit("Indique le poids de la bobine vide : --tare <g> (souvent 150 à 250 g).")
    b["tare_g"] = tare; b["reste_g"] = round(a.brut - tare, 1); sauver(d)
    print(f"#{b['id']} {b['nom']} : reste recalé à {b['reste_g']:.0f} g (pesée {a.brut:.0f} g - tare {tare:.0f} g)")


def cmd_corriger(a):
    d = charger(); b = bobine(d, a.id); b["reste_g"] = a.reste; sauver(d)
    print(f"#{b['id']} {b['nom']} : reste fixé à {a.reste:.0f} g")


def cmd_annuler(a):
    d = charger()
    if not d["historique"]:
        print("Historique vide."); return
    h = d["historique"].pop()
    for x in h["deductions"]:
        for b in d["bobines"]:
            if b["id"] == x["bobine"]:
                b["reste_g"] = round(b["reste_g"] + x["g"], 2)
    sauver(d)
    print(f"Annulé : {h['tache']} du {h['date']} ({h['total_g']:.1f} g rendus)")


def cmd_historique(a):
    d = charger()
    for h in d["historique"][-a.n:]:
        det = ", ".join(f"#{x['bobine']} {x['g']:.1f} g" for x in h["deductions"]) or "non attribué"
        print(f"{h['date']}  {h['total_g']:>7.1f} g  {h['tache']}  [{det}]")
    tot = sum(h["total_g"] for h in d["historique"])
    print(f"\nTotal enregistré : {tot:.0f} g sur {len(d['historique'])} impressions")


def cmd_supprimer(a):
    d = charger(); b = bobine(d, a.id)
    d["bobines"].remove(b)
    d["actives"] = {k: v for k, v in d["actives"].items() if v != a.id}
    sauver(d); print(f"Bobine #{a.id} {b['nom']} supprimée.")


def cmd_seuil(a):
    d = charger(); d["seuil_alerte_g"] = a.grammes; sauver(d)
    print(f"Seuil d'alerte : {a.grammes} g")


COMMANDES = {"ajouter", "liste", "activer", "peser", "corriger", "annuler", "historique", "supprimer", "seuil"}
JOURNAL = os.path.join(os.path.dirname(os.path.abspath(DATA)), "post_traitement.log")


def journal(*lignes):
    """Trace de chaque appel du slicer (diagnostic) : ~/SuiviFilament/post_traitement.log"""
    try:
        anciennes = []
        if os.path.exists(JOURNAL):
            with open(JOURNAL, encoding="utf-8", errors="replace") as f:
                anciennes = f.read().splitlines()[-300:]
        with open(JOURNAL, "w", encoding="utf-8") as f:
            f.write("\n".join(anciennes + [f"[{maintenant()}] {l}" for l in lignes]) + "\n")
    except OSError:
        pass


def main():
    # Mode post-traitement : le slicer passe le chemin du G-code en dernier argument.
    # Le fichier peut être une copie temporaire sans extension .gcode (ex. « piece.gcode.pp »),
    # donc tout fichier existant qui n'est pas une sous-commande est traité comme un G-code.
    args = sys.argv[1:]
    if args and args[0] not in COMMANDES and not args[0].startswith("-") and os.path.isfile(args[-1]):
        chemin = args[-1]
        journal(f"appel du slicer : fichier={chemin} | sortie={os.environ.get('SLIC3R_PP_OUTPUT_NAME', '-')} "
                f"| hôte={os.environ.get('SLIC3R_PP_HOST', '-')}")
        try:
            post_traitement(chemin)
        except Exception as e:  # ne jamais bloquer l'export du slicer
            journal(f"  erreur : {e!r}")
            print(f"suivi_filament : erreur ignorée ({e})", file=sys.stderr)
        return

    p = argparse.ArgumentParser(description="Suivi des bobines de filament")
    s = p.add_subparsers(dest="cmd", required=True)

    x = s.add_parser("ajouter", help="ajouter une bobine")
    x.add_argument("--nom", required=True); x.add_argument("--matiere", default="PLA")
    x.add_argument("--couleur", default=""); x.add_argument("--poids", type=float, default=1000, help="poids net neuf (g)")
    x.add_argument("--reste", type=float, help="reste actuel si déjà entamée (g)")
    x.add_argument("--tare", type=float, help="poids bobine vide (g)")
    x.add_argument("--prix", type=float, help="prix au kg (€)")
    x.add_argument("--emplacement", type=int, help="l'activer sur cet emplacement (1 à 4)")
    x.set_defaults(f=cmd_ajouter)

    s.add_parser("liste", help="état des bobines").set_defaults(f=cmd_liste)

    x = s.add_parser("activer", help="bobine chargée sur un emplacement")
    x.add_argument("id", type=int); x.add_argument("--emplacement", type=int, default=1); x.set_defaults(f=cmd_activer)

    x = s.add_parser("peser", help="recaler le reste avec une pesée")
    x.add_argument("id", type=int); x.add_argument("--brut", type=float, required=True)
    x.add_argument("--tare", type=float); x.set_defaults(f=cmd_peser)

    x = s.add_parser("corriger", help="fixer le reste à la main")
    x.add_argument("id", type=int); x.add_argument("--reste", type=float, required=True); x.set_defaults(f=cmd_corriger)

    s.add_parser("annuler", help="annuler la dernière impression (ratée, pas lancée...)").set_defaults(f=cmd_annuler)

    x = s.add_parser("historique", help="dernières impressions")
    x.add_argument("-n", type=int, default=20); x.set_defaults(f=cmd_historique)

    x = s.add_parser("supprimer", help="supprimer une bobine")
    x.add_argument("id", type=int); x.set_defaults(f=cmd_supprimer)

    x = s.add_parser("seuil", help="seuil d'alerte bobine presque vide (g)")
    x.add_argument("grammes", type=float); x.set_defaults(f=cmd_seuil)

    a = p.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
