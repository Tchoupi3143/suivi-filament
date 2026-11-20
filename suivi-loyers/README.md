# Suivi Loyers

**Surveille le compte bancaire qui reçoit tes loyers, repère qui a payé et envoie
automatiquement la quittance au locataire dès que son loyer est réglé.**

- **Connexion directe à la banque** (lecture seule, DSP2) via Enable Banking, gratuit pour ses
  propres comptes : chaque jour, les nouvelles opérations sont récupérées toutes seules, sans
  fichier à télécharger. Banque Populaire (chaque banque régionale) et la plupart des banques européennes.
- **Ou lecture des relevés** : OFX/QFX, CSV, QIF (toutes les banques françaises) et CAMT.053.
- **Reconnaissance des virements** par mots du libellé (nom du locataire, du conjoint, du garant,
  de la CAF…). Un virement non reconnu n'est **jamais** attribué au hasard : il est mis
  « à vérifier », avec une suggestion d'après le montant, à confirmer en un clic.
- **Suivi mois par mois** : payé, partiel, attendu, en retard, payé d'avance. Les paiements en
  plusieurs fois, les avances et les révisions de loyer (IRL) sont gérés.
- **Quittance PDF automatique** (art. 21 de la loi du 6 juillet 1989 : loyer et charges détaillés,
  montant en lettres, date du paiement) envoyée par e-mail au locataire, avec copie cachée pour toi.
  En cas de paiement partiel : **reçu** (et non quittance), à envoyer en un clic.
- **Relance** en un clic pour un loyer en retard.
- **Tout tourne sur ton ordinateur** : l'e-mail part de ta propre boîte (Gmail, Outlook, Orange,
  Free, OVH…) ; seule la lecture du compte passe par Enable Banking.

Python 3.8 ou plus récent, bibliothèque standard uniquement : rien à installer.

## Démarrage

1. **Mac** : dézippe `SuiviLoyers-mac-*.zip` et glisse **Suivi Loyers.app** dans **Applications**
   (puis dans le Dock si tu veux). Premier lancement : **clic droit › Ouvrir › Ouvrir** (l'application
   n'est pas signée par Apple). Si macOS la dit « endommagée » :
   ```bash
   xattr -cr "/Applications/Suivi Loyers.app"
   ```
   L'interface s'ouvre dans le navigateur ; un nouveau double-clic rouvre le même onglet. L'application
   s'arrête avec le bouton « Quitter » ou 30 minutes après la fermeture de l'onglet ; la vérification
   quotidienne, elle, tourne même application fermée.
   **Windows / Linux** : double-clic sur **`Suivi Loyers.bat`** ou **`Suivi Loyers.command`**,
   ou `python3 src/serveur.py`.
2. **Réglages** : ton nom ou celui de la SCI, ton adresse, puis le compte e-mail d'envoi.
   Clique sur « Envoyer un e-mail de test ».
   - Gmail : `smtp.gmail.com`, port 465, avec un **mot de passe d'application**
     (Compte Google › Sécurité › Validation en deux étapes › Mots de passe des applications).
   - Outlook : `smtp-mail.outlook.com`, port 587 (STARTTLS).
3. **＋ Logement** pour chaque appartement : locataire, e-mail, adresse, loyer hors charges,
   provision pour charges, jour d'échéance et **mots à reconnaître** dans le libellé du virement
   (ex. `DUPONT`, ou `CAF 1234567` pour l'APL versée directement).
4. **Banque** : relie le compte des loyers (ci-dessous) et active la vérification quotidienne.

## Connexion automatique à la banque

Une seule mise en place, d'environ 15 minutes. Ensuite plus rien à faire, sauf renouveler
l'autorisation tous les 180 jours au plus (exigence des banques ; un e-mail te prévient 10 jours avant).

1. **Compte Enable Banking** : crée un compte sur [enablebanking.com](https://enablebanking.com/sign-in/),
   puis dans le [panneau de contrôle](https://enablebanking.com/cp/applications) :
   « Register new application » › environnement **Production**, nom « Suivi Loyers »,
   URL de redirection **`https://example.com/redirect`** (tape-la à la main ; `localhost` est
   refusé), clé « **Generate in the browser** » : un fichier `.pem` (ta clé privée) se télécharge.
   `example.com` est un domaine réservé aux exemples : le code qui y transite est inutilisable
   sans ta clé.
2. Sur l'application créée : **« Activate by linking accounts »** et relie le compte qui reçoit
   les loyers. C'est le « mode restreint », gratuit, limité à tes propres comptes.
3. Dans Suivi Loyers, bouton **Banque** : colle l'*Application ID*, choisis le fichier `.pem`,
   « Charger la liste », choisis **ta Banque Populaire régionale**, puis « Se connecter à la banque ».
4. Valide sur le site de ta banque (Secur'Pass). Tu arrives sur une page « Example Domain »
   (, c'est normal) : copie son adresse depuis la barre du navigateur et
   colle-la dans Suivi Loyers. Les opérations des 90 derniers jours sont récupérées aussitôt.
5. **« Activer »** la vérification quotidienne : ton ordinateur interroge la banque chaque jour,
   même interface fermée, reconnaît les loyers et envoie les quittances.

Sécurité : accès en **lecture seule** (aucun virement possible), aucun identifiant bancaire saisi
dans Suivi Loyers, clé privée rangée dans `~/SuiviLoyers/enablebanking.pem`, lisible par toi seul.
Les opérations transitent par Enable Banking (prestataire agréé DSP2, Finlande).

**Bankin'** n'est pas nécessaire : l'application ne propose pas d'accès pour un particulier
(son API, Bridge, est réservée aux entreprises).

## Sans connexion bancaire : relevés

Tout relevé importé depuis l'interface (bouton ou glisser-déposer) ou déposé dans
**`~/SuiviLoyers/a-importer/`** est traité. Importer deux fois le même relevé ne compte rien en double.

Banque Populaire, site Cyberplus : synthèse des comptes › **« Gérer »** › **« Télécharger les
opérations »** › format **Money (.ofx)** (ou Excel .csv avec « ; », ou Quicken .qif). Si « Gérer »
manque : ton nom en haut à droite › « Autres réglages » › « Fonctionnalités avancées ».

## Vérification quotidienne et commandes

La vérification quotidienne utilise launchd (macOS, rattrapée au réveil si l'ordinateur dormait),
le Planificateur de tâches (Windows) ou cron (Linux). Elle s'exécute sur ton ordinateur : s'il reste
éteint plusieurs jours, elle a lieu au rallumage. Journal : `~/SuiviLoyers/scan.log`.

```bash
python3 src/loyers.py scan                        # banque + dossier a-importer, quittances, état du mois
python3 src/loyers.py scan releve.ofx autre.csv   # importer des fichiers précis
python3 src/loyers.py scan --sans-envoi           # tout calculer sans envoyer d'e-mail
python3 src/loyers.py statut 2026-11              # état d'un mois
python3 src/planifier.py 09:00                    # installer la vérification quotidienne
python3 src/planifier.py --retirer
```

Mots à reconnaître : un virement reçu porte le nom du payeur (`M JEAN DUPONT`) et le motif saisi
par le locataire. Le **nom de famille** suffit en général ; ouvre « Opérations du compte » après
la première synchronisation pour vérifier.

## Règles appliquées

- Chaque virement compte d'abord pour **le mois où il est reçu** ; ce qui dépasse complète un mois
  précédent resté incomplet (le plus ancien d'abord), puis paie d'avance les mois suivants. Un petit
  manque sur un mois reste donc sur ce mois (« partiel ») sans décaler les suivants. Quand un virement
  est réparti sur plusieurs mois, la colonne « Reçu » l'explique.
- La quittance est émise quand le mois est **entièrement** réglé ; sa date de paiement est celle du
  virement qui a soldé le mois. Un mois payé d'avance reçoit sa quittance le 1er du mois.
- Seules les opérations **comptabilisées** comptent (pas celles « en cours »).
- **Envoi automatique limité au mois en cours et au précédent** : au premier import d'un historique,
  les anciennes quittances sont générées mais pas envoyées (bouton « Envoyer » si besoin).
- Une quittance n'est jamais envoyée deux fois automatiquement. Si l'envoi échoue (réseau, mot de
  passe), il est retenté au passage suivant.
- Un loyer est « en retard » après le jour d'échéance + le délai de grâce (5 jours par défaut).
- Révision de loyer : dans « Modifier », change le montant et indique le mois d'application ;
  les mois précédents gardent l'ancien montant.
- **Entrée en cours de mois** : indique la date d'entrée ; le premier mois est calculé au prorata
  des jours (ou au montant saisi), et la quittance porte la période réelle (« du 15 au 30 novembre »).
  Même chose pour une date de sortie.
- **Dépôt de garantie** : indique son montant. Un virement paie d'abord son mois, puis un arriéré,
  puis le dépôt, puis les mois suivants : le virement d'entrée (prorata + mois suivant + dépôt) est
  donc réparti tout seul. Le dépôt n'apparaît jamais sur une quittance.
- Chèque, espèces : « Paiement manuel ».

## Données

| Emplacement | Contenu |
|---|---|
| `~/SuiviLoyers/donnees.json` | logements, opérations, quittances, journal |
| `~/SuiviLoyers/quittances/` | les PDF, rangés par locataire |
| `~/SuiviLoyers/.smtp` | mot de passe e-mail (lisible par toi seul) — ou variable `SUIVI_LOYERS_SMTP_MDP` |
| `~/SuiviLoyers/enablebanking.pem` | clé privée de ton application Enable Banking (lisible par toi seul) |
| `~/SuiviLoyers/moteur/` | copie du programme utilisée par la vérification quotidienne |

Dossier modifiable avec la variable d'environnement `SUIVI_LOYERS_DOSSIER`. L'interface n'écoute
que sur `127.0.0.1` et exige un jeton aléatoire généré à chaque lancement.

## Limites

- La gratuité du mode restreint d'Enable Banking (usage personnel non commercial) dépend de ses
  conditions, qui peuvent évoluer ; les relevés restent une solution de secours. Les banques
  limitent les consultations automatiques : une par jour suffit.
- La restitution du dépôt de garantie en fin de bail n'est pas suivie.
- Les rejets de virement apparaissent comme des débits : détache le virement rejeté.

## Développement

```
src/loyers.py      moteur : import, rapprochement, soldes, quittances, CLI
src/banque.py      connexion Enable Banking (JWT RS256 signé en Python pur)
src/planifier.py   vérification quotidienne (launchd / Planificateur de tâches / cron)
src/releves.py     lecture OFX / CSV / QIF / CAMT.053
src/quittance.py   génération du PDF (générateur PDF intégré, montant en lettres)
src/envoi.py       envoi SMTP
src/serveur.py     serveur local de l'interface
src/index.html     interface
macos/             lanceur, Info.plist et icône (icone.svg -> src/AppIcon.icns, src/icone.png)
build.py           construit dist/SuiviLoyers-mac-<version>.zip (Suivi Loyers.app)
tests/             tests unitaires (faux serveurs SMTP et Enable Banking)
exemples/          relevés d'exemple
```

```bash
python3 -m unittest discover -s tests
python3 build.py
```

Essai sans toucher à tes données :

```bash
SUIVI_LOYERS_DOSSIER=/tmp/essai-loyers python3 src/serveur.py
```

Licence [GPL-3.0-or-later](../LICENSE).
