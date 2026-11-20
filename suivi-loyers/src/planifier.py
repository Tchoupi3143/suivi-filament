#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Installe (ou retire) la vérification quotidienne : « loyers.py scan » chaque jour à l'heure choisie.

    python3 planifier.py [HH:MM]      # installer (9:00 par défaut)
    python3 planifier.py --retirer
    python3 planifier.py --etat

macOS : agent launchd (rattrapé au réveil si l'ordinateur dormait à l'heure prévue).
Windows : tâche planifiée « Suivi Loyers ».   Linux : ligne crontab.
"""
import os
import plistlib
import shutil
import subprocess
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
DOSSIER = os.path.expanduser(os.environ.get("SUIVI_LOYERS_DOSSIER", "~/SuiviLoyers"))
# copie du moteur dans le dossier de données : la tâche reste valable si le dossier du programme est
# déplacé, et macOS n'empêche pas l'agent de lire Documents/Téléchargements (protection de la vie privée)
COPIE = os.path.join(DOSSIER, "moteur")
MOTEUR = os.path.join(COPIE, "loyers.py")
JOURNAL = os.path.join(DOSSIER, "scan.log")
NOM = "fr.suiviloyers.scan"
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{NOM}.plist")
TACHE = "Suivi Loyers"
MARQUE = "# suivi-loyers"


def _cron():
    r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def copier_moteur():
    os.makedirs(COPIE, exist_ok=True)
    for f in ("loyers.py", "releves.py", "quittance.py", "envoi.py", "banque.py"):
        shutil.copy2(os.path.join(ICI, f), os.path.join(COPIE, f))


def installer(heure="09:00"):
    h, m = (int(x) for x in heure.split(":"))
    copier_moteur()
    if sys.platform == "darwin":
        env = {"SUIVI_LOYERS_DOSSIER": DOSSIER, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
        with open(PLIST, "wb") as f:
            plistlib.dump({"Label": NOM, "ProgramArguments": [sys.executable, MOTEUR, "scan"],
                           "StartCalendarInterval": {"Hour": h, "Minute": m}, "EnvironmentVariables": env,
                           "StandardOutPath": JOURNAL, "StandardErrorPath": JOURNAL}, f)
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        r = subprocess.run(["launchctl", "load", PLIST], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or "launchctl a refusé l'agent")
    elif os.name == "nt":
        python = sys.executable.replace("python.exe", "pythonw.exe")
        if not os.path.exists(python):
            python = sys.executable
        r = subprocess.run(["schtasks", "/Create", "/F", "/SC", "DAILY", "/ST", f"{h:02d}:{m:02d}", "/TN", TACHE,
                            "/TR", f'"{python}" "{MOTEUR}" scan'], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    else:
        lignes = [l for l in _cron().splitlines() if MARQUE not in l]
        lignes.append(f'{m} {h} * * * SUIVI_LOYERS_DOSSIER="{DOSSIER}" "{sys.executable}" "{MOTEUR}" scan '
                      f'>> "{JOURNAL}" 2>&1 {MARQUE}')
        r = subprocess.run(["crontab", "-"], input="\n".join(lignes) + "\n", capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or "crontab a refusé la ligne")
    return f"Vérification quotidienne installée ({h:02d}:{m:02d})"


def retirer():
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "unload", PLIST], capture_output=True)
        if os.path.exists(PLIST):
            os.remove(PLIST)
    elif os.name == "nt":
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", TACHE], capture_output=True)
    else:
        lignes = [l for l in _cron().splitlines() if MARQUE not in l]
        subprocess.run(["crontab", "-"], input="\n".join(lignes) + "\n" if lignes else "", capture_output=True, text=True)
    return "Vérification quotidienne retirée"


def etat():
    """Heure planifiée (« HH:MM ») ou None."""
    try:
        if sys.platform == "darwin":
            with open(PLIST, "rb") as f:
                c = plistlib.load(f)["StartCalendarInterval"]
            return f"{c['Hour']:02d}:{c['Minute']:02d}"
        if os.name == "nt":
            r = subprocess.run(["schtasks", "/Query", "/TN", TACHE, "/FO", "LIST"], capture_output=True, text=True)
            return "planifiée" if r.returncode == 0 else None
        for l in _cron().splitlines():
            if MARQUE in l:
                m, h = l.split()[:2]
                return f"{int(h):02d}:{int(m):02d}"
    except Exception:
        pass
    return None


if __name__ == "__main__":
    a = sys.argv[1:]
    try:
        if "--retirer" in a:
            print(retirer())
        elif "--etat" in a:
            print(etat() or "non planifiée")
        else:
            print(installer(a[0] if a else "09:00"))
    except Exception as e:
        sys.exit(f"Échec : {e}")
