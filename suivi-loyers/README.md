# Suivi Loyers

**Surveille le compte bancaire qui reçoit tes loyers, repère qui a payé et envoie
automatiquement la quittance au locataire dès que son loyer est réglé.**

- **Lecture des relevés** : OFX/QFX, CSV (toutes les banques françaises) et CAMT.053 (XML ISO 20022).
- **Reconnaissance des virements** par mots du libellé (nom du locataire, du conjoint, du garant,
  de la CAF…). Un virement non reconnu n'est **jamais** attribué au hasard : il est mis
  « à vérifier », avec une suggestion d'après le montant, à confirmer en un clic.
- **Suivi mois par mois** : payé, partiel, attendu, en retard, payé d'avance. Les paiements en
  plusieurs fois, les avances et les révisions de loyer (IRL) sont gérés.
- **Quittance PDF automatique** (art. 21 de la loi du 6 juillet 1989 : loyer et charges détaillés,
  montant en lettres, date du paiement) envoyée par e-mail au locataire, avec copie cachée pour toi.
  En cas de paiement partiel : **reçu** (et non quittance), à envoyer en un clic.
- **Relance** en un clic pour un loyer en retard.
- **Tout reste sur ton ordinateur** : aucun compte, aucun serveur externe ; l'e-mail part de ta
  propre boîte (Gmail, Outlook, Orange, Free, OVH…).

Python 3.8 ou plus récent, bibliothèque standard uniquement : rien à installer.

## Démarrage

1. Double-clique sur **`Suivi Loyers.command`** (macOS/Linux) ou **`Suivi Loyers.bat`** (Windows),
   ou lance `python3 src/serveur.py`. L'interface s'ouvre dans le navigateur.
2. **Réglages** : ton nom ou celui de la SCI, ton adresse, puis le compte e-mail d'envoi.
   Clique sur « Envoyer un e-mail de test ».
   - Gmail : `smtp.gmail.com`, port 465, avec un **mot de passe d'application**
     (Compte Google › Sécurité › Validation en deux étapes › Mots de passe des applications).
   - Outlook : `smtp-mail.outlook.com`, port 587 (STARTTLS).
3. **＋ Logement** pour chaque appartement : locataire, e-mail, adresse, loyer hors charges,
   provision pour charges, jour d'échéance et **mots à reconnaître** dans le libellé du virement
   (ex. `DUPONT`, ou `CAF 1234567` pour l'APL versée directement).
4. **Importe un relevé** exporté depuis l'espace client de ta banque (bouton, ou glisser-déposer
   sur la page). Les virements reconnus sont affectés, les quittances générées et envoyées.

Importer deux fois le même relevé, ou des relevés qui se chevauchent, ne compte rien en double
(et une même opération présente dans un export CSV puis OFX est repérée comme doublon).

## Automatiser

Tout relevé déposé dans **`~/SuiviLoyers/a-importer/`** est traité par la commande :

```bash
python3 src/loyers.py scan
```

Elle importe les fichiers, les range dans `importes/`, reconnaît les paiements, génère et envoie
les quittances, puis affiche l'état du mois. À planifier une fois par jour :

- **macOS / Linux** (`crontab -e`) :
  ```
  0 9 * * * /usr/bin/python3 /chemin/vers/suivi-loyers/src/loyers.py scan >> ~/SuiviLoyers/scan.log 2>&1
  ```
- **Windows** (invite de commandes) :
  ```
  schtasks /Create /SC DAILY /ST 09:00 /TN "Suivi Loyers" /TR "py -3 C:\chemin\suivi-loyers\src\loyers.py scan"
  ```

Astuce : règle le dossier de téléchargement de ton navigateur (ou de l'app de ta banque) sur
`~/SuiviLoyers/a-importer/` : il suffit alors de cliquer sur « Exporter » dans l'espace client.
Quand l'interface est ouverte, ce dossier est aussi surveillé chaque minute.

Autres commandes :

```bash
python3 src/loyers.py scan releve.ofx autre.csv   # importer des fichiers précis
python3 src/loyers.py scan --sans-envoi           # tout calculer sans envoyer d'e-mail
python3 src/loyers.py statut 2026-11              # état d'un mois
```

## Règles appliquées

- Les paiements d'un logement sont imputés **au mois impayé le plus ancien** : un virement de
  rattrapage solde d'abord l'arriéré ; un trop-versé est reporté sur le mois suivant (payé d'avance).
- La quittance est émise quand le mois est **entièrement** réglé ; sa date de paiement est celle du
  virement qui a soldé le mois. Un mois payé d'avance reçoit sa quittance le 1er du mois.
- **Envoi automatique limité au mois en cours et au précédent** : au premier import d'un historique,
  les anciennes quittances sont générées mais pas envoyées (bouton « Envoyer » si besoin).
- Une quittance n'est jamais envoyée deux fois automatiquement. Si l'envoi échoue (réseau, mot de
  passe), il est retenté au passage suivant.
- Un loyer est « en retard » après le jour d'échéance + le délai de grâce (5 jours par défaut).
- Révision de loyer : dans « Modifier », change le montant et indique le mois d'application ;
  les mois précédents gardent l'ancien montant.
- Chèque, espèces : « Paiement manuel ».

## Données

| Emplacement | Contenu |
|---|---|
| `~/SuiviLoyers/donnees.json` | logements, opérations, quittances, journal |
| `~/SuiviLoyers/quittances/` | les PDF, rangés par locataire |
| `~/SuiviLoyers/.smtp` | mot de passe e-mail (lisible par toi seul) — ou variable `SUIVI_LOYERS_SMTP_MDP` |

Dossier modifiable avec la variable d'environnement `SUIVI_LOYERS_DOSSIER`. L'interface n'écoute
que sur `127.0.0.1` et exige un jeton aléatoire généré à chaque lancement.

## Limites

- **Pas de connexion directe à la banque** : les banques françaises ne proposent pas d'accès
  automatique gratuit pour un particulier ; l'accès DSP2 passe par des agrégateurs payants ou sur
  dossier. L'outil lit donc les exports de relevés. Les comptes pros Qonto / Shine disposent d'une
  API qui pourrait être branchée sur `loyers.importer()`.
- Pas de prorata automatique pour un mois d'entrée ou de sortie incomplet : saisis le montant
  du premier mois via une révision de loyer, ou ajuste à la main.
- Le dépôt de garantie, s'il est versé par le locataire avec un libellé reconnu, serait compté
  comme loyer : fais commencer le bail au premier mois de loyer et ignore ce virement
  (« Opérations du compte » › Détacher, puis Ignorer).
- Les rejets de virement apparaissent comme des débits : détache le virement rejeté.

## Développement

```
src/loyers.py      moteur : import, rapprochement, soldes, quittances, CLI
src/releves.py     lecture OFX / CSV / CAMT.053
src/quittance.py   génération du PDF (générateur PDF intégré, montant en lettres)
src/envoi.py       envoi SMTP
src/serveur.py     serveur local de l'interface
src/index.html     interface
tests/             tests unitaires (avec un faux serveur SMTP)
exemples/          relevés d'exemple
```

```bash
python3 -m unittest discover -s tests
```

Essai sans toucher à tes données :

```bash
SUIVI_LOYERS_DOSSIER=/tmp/essai-loyers python3 src/serveur.py
```

Licence [GPL-3.0-or-later](../LICENSE).
