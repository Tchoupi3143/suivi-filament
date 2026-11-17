#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tchoupi3143 — Suivi Filament
"""
Ajoute le suivi filament aux « Scripts de post-traitement » de tes profils de
traitement personnels ElegooSlicer (macOS).

    python3 configurer_slicer.py <commande_post_traitement>        # installer
    python3 configurer_slicer.py --retirer <commande_post_traitement>  # désinstaller

- ElegooSlicer doit être FERMÉ (sinon il écrase la modification en quittant).
- Seuls les profils personnels (enregistrés avec l'icône disquette) sont modifiables ;
  les profils Elegoo d'origine sont en lecture seule.
- Une sauvegarde .bak-suivi de chaque profil est faite avant modification.
"""
import glob
import json
import os
import shutil
import sys

SUPPORT = os.path.expanduser("~/Library/Application Support")
DOSSIERS = ["*legoo*licer*"]          # ElegooSlicer (quelle que soit la casse/variante)


def profils():
    trouves = []
    for motif in DOSSIERS:
        for base in glob.glob(os.path.join(SUPPORT, motif)):
            trouves += glob.glob(os.path.join(base, "user", "*", "process", "*.json"))
    return sorted(trouves)


def main():
    args = sys.argv[1:]
    retirer = "--retirer" in args
    args = [a for a in args if a != "--retirer"]
    if len(args) != 1:
        sys.exit(__doc__)
    cmd = args[0]

    bases = [b for m in DOSSIERS for b in glob.glob(os.path.join(SUPPORT, m))]
    if not bases:
        print("ElegooSlicer ne semble pas installé (aucun dossier de réglages trouvé).")
        return 2
    fichiers = profils()
    if not fichiers:
        print("Aucun profil de traitement personnel trouvé.")
        print("Dans ElegooSlicer : onglet Process, change un réglage (ou pas), clique sur l'icône")
        print("disquette pour l'enregistrer sous ton propre nom, ferme ElegooSlicer et relance l'installeur.")
        return 3

    modifies = 0
    for f in fichiers:
        try:
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as e:
            print(f"  ignoré (illisible) : {os.path.basename(f)} ({e})")
            continue
        pp = d.get("post_process", [])
        if isinstance(pp, str):
            pp = [pp] if pp else []
        pp = [s for s in pp if s.strip()]
        if retirer:
            nouveau = [s for s in pp if cmd not in s]
        else:
            if any(cmd in s for s in pp):
                print(f"  déjà configuré : {d.get('name', os.path.basename(f))}")
                continue
            nouveau = pp + [cmd]
        if nouveau == pp:
            continue
        shutil.copy2(f, f + ".bak-suivi")
        if nouveau:
            d["post_process"] = nouveau
        else:
            d.pop("post_process", None)
        tmp = f + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=4)
        os.replace(tmp, f)
        modifies += 1
        print(f"  {'retiré de' if retirer else 'ajouté à'} : {d.get('name', os.path.basename(f))}")

    print(f"{modifies} profil(s) modifié(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
