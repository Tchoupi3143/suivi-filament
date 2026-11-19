# SPDX-License-Identifier: GPL-3.0-or-later
"""Envoi des quittances par e-mail (SMTP, bibliothèque standard)."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid


def mot_de_passe(dossier):
    if os.environ.get("SUIVI_LOYERS_SMTP_MDP"):
        return os.environ["SUIVI_LOYERS_SMTP_MDP"]
    try:
        with open(os.path.join(dossier, ".smtp"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def enregistrer_mot_de_passe(dossier, mdp):
    chemin = os.path.join(dossier, ".smtp")
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(mdp)


def configure(smtp):
    return bool(smtp.get("hote") and smtp.get("expediteur"))


def envoyer(smtp, dossier, a, sujet, texte, pieces=(), copie=None):
    """pieces : [(nom_fichier, octets)] (PDF). Lève une exception en cas d'échec."""
    if not configure(smtp):
        raise RuntimeError("Envoi d'e-mails non configuré (Réglages > E-mail)")
    msg = EmailMessage()
    msg["From"] = formataddr((smtp.get("nom_expediteur") or "", smtp["expediteur"]))
    msg["To"] = a
    if copie:
        msg["Bcc"] = copie
    msg["Subject"] = sujet
    msg["Message-ID"] = make_msgid(domain=smtp["expediteur"].split("@")[-1])
    msg.set_content(texte)
    for nom, octets in pieces:
        msg.add_attachment(octets, maintype="application", subtype="pdf", filename=nom)
    port = int(smtp.get("port") or 465)
    securite = smtp.get("securite") or ("ssl" if port == 465 else "starttls")   # « aucune » : relais local
    contexte = ssl.create_default_context()
    if securite == "ssl":
        serveur = smtplib.SMTP_SSL(smtp["hote"], port, context=contexte, timeout=30)
    else:
        serveur = smtplib.SMTP(smtp["hote"], port, timeout=30)
    with serveur:
        if securite == "starttls":
            serveur.starttls(context=contexte)
        utilisateur = smtp.get("utilisateur") or smtp["expediteur"]
        mdp = mot_de_passe(dossier)
        if mdp:
            serveur.login(utilisateur, mdp)
        serveur.send_message(msg)
