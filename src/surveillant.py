#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Tchoupi3143 — Suivi Filament
"""
Surveillant : détecte les G-code produits par ElegooSlicer, sans qu'ElegooSlicer ait à l'appeler.

- Envoi à l'imprimante : ElegooSlicer écrit le G-code dans un fichier temporaire
  « .ElegooSlicer.upload.<id> » du dossier temporaire de l'utilisateur, puis l'envoie.
- Export : fichiers *.gcode nouvellement créés dans Téléchargements et sur le Bureau.

Le surveillant ne fait que LIRE ces fichiers : il ne peut ni les modifier ni bloquer une impression.
Il est lancé en arrière-plan par macOS (LaunchAgent) à l'ouverture de session.

Variables utiles (tests) : SUIVI_FILAMENT_TMP, SUIVI_FILAMENT_EXPORTS (dossiers séparés par « : »),
SUIVI_FILAMENT_DUREE (arrêt après N secondes).
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import suivi_filament as sf   # noqa: E402

PREFIXES_ENVOI = (".ElegooSlicer.upload", ".OrcaSlicer.upload")   # fichiers temporaires d'envoi
STABLE_S = 1.0        # le fichier n'a plus grossi depuis 1 s : il est complet
PATIENCE_S = 20.0     # au-delà, on traite même sans ligne de consommation
OUBLI_S = 900         # on cesse de suivre un fichier au bout de 15 min
ETAT = os.path.join(os.path.dirname(os.path.abspath(sf.DATA)), "surveillant.etat")


def dossier_temp():
    if os.environ.get("SUIVI_FILAMENT_TMP"):
        return os.environ["SUIVI_FILAMENT_TMP"]
    if sys.platform == "darwin":
        # le dossier temporaire « par utilisateur » de macOS (/var/folders/…/T/), le même qu'ElegooSlicer
        try:
            r = subprocess.run(["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass
    return os.environ.get("TMPDIR", "/tmp")


def dossiers_export():
    if "SUIVI_FILAMENT_EXPORTS" in os.environ:
        return [d for d in os.environ["SUIVI_FILAMENT_EXPORTS"].split(":") if d]
    return [os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")]


class Fichier:
    """Un G-code en cours d'écriture : on garde le fichier ouvert, il reste lisible même s'il est supprimé."""

    def __init__(self, chemin, origine):
        self.chemin, self.origine = chemin, origine
        self.f = open(chemin, "rb")
        self.vu = time.time()
        self.taille, self.depuis = -1, time.time()

    def inode_change(self):
        try:
            return os.stat(self.chemin).st_ino != os.fstat(self.f.fileno()).st_ino
        except OSError:
            return False          # supprimé : on garde notre copie ouverte

    def pret(self):
        t = os.fstat(self.f.fileno()).st_size
        if t != self.taille:
            self.taille, self.depuis = t, time.time()
            return False
        if t == 0 or time.time() - self.depuis < STABLE_S:
            return False
        fin = self.lire_fin()
        return b"filament used [g]" in fin or b"filament used [mm]" in fin or time.time() - self.depuis > PATIENCE_S

    def lire_fin(self):
        self.f.seek(max(0, self.taille - 200_000))
        return self.f.read()

    def contenu(self):
        self.f.seek(0)
        return self.f.read().decode("utf-8", "replace")

    def fermer(self):
        try:
            self.f.close()
        except OSError:
            pass


class Surveillant:
    def __init__(self):
        self.tmp = dossier_temp()
        self.exports = dossiers_export()
        self.debut = time.time()
        self.suivis = {}            # chemin -> Fichier
        self.deja = set()           # (chemin, mtime) déjà vus
        self.erreurs_dossiers = set()
        self.dernier_export_scan = 0.0

    def candidats_envoi(self):
        try:
            with os.scandir(self.tmp) as it:
                for e in it:
                    if e.name.startswith(PREFIXES_ENVOI) and e.is_file():
                        yield e.path, "envoi"
        except OSError as err:
            self.signaler(self.tmp, err)

    def candidats_export(self):
        for d in self.exports:
            try:
                with os.scandir(d) as it:
                    for e in it:
                        if e.name.lower().endswith(".gcode") and not e.name.startswith(".") and e.is_file():
                            if e.stat().st_mtime >= self.debut - 2:
                                yield e.path, "export"
            except OSError as err:
                self.signaler(d, err)

    def signaler(self, dossier, err):
        if dossier not in self.erreurs_dossiers:
            self.erreurs_dossiers.add(dossier)
            sf.journal(f"surveillant : dossier inaccessible {dossier} ({err.strerror or err})")

    def tour(self):
        candidats = list(self.candidats_envoi())
        if time.time() - self.dernier_export_scan > 2:
            self.dernier_export_scan = time.time()
            candidats += list(self.candidats_export())
        for chemin, origine in candidats:
            try:
                cle = (chemin, os.stat(chemin).st_mtime_ns)
            except OSError:
                continue
            if chemin in self.suivis or cle in self.deja:
                continue
            try:
                self.suivis[chemin] = Fichier(chemin, origine)
                self.deja.add(cle)
            except OSError:
                continue
        for chemin, fi in list(self.suivis.items()):
            try:
                if fi.inode_change():               # remplacé par un nouveau fichier : on le reprendra
                    fi.fermer(); del self.suivis[chemin]; continue
                if fi.pret():
                    self.traiter(fi)
                    fi.fermer(); del self.suivis[chemin]
                elif time.time() - fi.vu > OUBLI_S:
                    fi.fermer(); del self.suivis[chemin]
            except Exception as e:                  # ne jamais s'arrêter sur un fichier
                sf.journal(f"surveillant : erreur sur {chemin} ({e!r})")
                fi.fermer(); self.suivis.pop(chemin, None)

    def traiter(self, fi):
        nom = os.path.basename(fi.chemin)
        if fi.origine == "envoi":
            nom = "Impression envoyée à l'imprimante"
        sf.journal(f"G-code détecté ({fi.origine}) : {fi.chemin}")
        sf.comptabiliser(fi.contenu(), nom, origine=fi.origine, notification=True)

    def ecrire_etat(self):
        try:
            tmp = ETAT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "signe": time.time(), "depuis": self.debut,
                           "dossier_temp": self.tmp, "exports": self.exports,
                           "inaccessibles": sorted(self.erreurs_dossiers)}, f)
            os.replace(tmp, ETAT)
        except OSError:
            pass

    def boucle(self, duree=None):
        sf.journal(f"surveillant démarré (temp : {self.tmp} ; exports : {', '.join(self.exports)})")
        dernier_etat = 0.0
        while duree is None or time.time() - self.debut < duree:
            self.tour()
            if time.time() - dernier_etat > 5:
                self.ecrire_etat(); dernier_etat = time.time()
            time.sleep(0.25)


if __name__ == "__main__":
    duree = float(os.environ["SUIVI_FILAMENT_DUREE"]) if os.environ.get("SUIVI_FILAMENT_DUREE") else None
    Surveillant().boucle(duree)
