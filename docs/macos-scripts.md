# Suivi filament pour ElegooSlicer — macOS

À chaque **export ou envoi d'un G-code**, retire les grammes consommés du stock de ta bobine,
garde un historique et **affiche une alerte macOS s'il ne reste pas assez de filament**.

## 1. Installation (automatique)

**Avant :** dans ElegooSlicer, assure-toi d'avoir un **profil de traitement personnel** :
onglet **Process** → icône **disquette** → enregistre-le sous ton nom. (Les profils Elegoo
d'origine ne peuvent pas être modifiés.) Puis **quitte ElegooSlicer (⌘Q)**.

1. Dézippe le dossier.
2. **Clic droit sur `installer.command` → Ouvrir → Ouvrir**
   (le clic droit est nécessaire la première fois : macOS bloque les scripts téléchargés).
3. L'installeur :
   - trouve Python (s'il manque : `xcode-select --install` dans le Terminal, puis relance) ;
   - installe tout dans `~/SuiviFilament` et ajoute la commande `bobines` au Terminal ;
   - **ajoute le suivi à tous tes profils de traitement personnels d'ElegooSlicer**
     (une copie `.bak-suivi` de chaque profil est gardée) ;
   - si ElegooSlicer est encore ouvert, il te demande de le quitter et attend.

Rouvre ElegooSlicer : dans Process → mode Avancé → Autres → Scripts de post-traitement,
tu verras le chemin `/Users/ton-nom/SuiviFilament/bobines`.

> Si l'installeur ne trouve aucun profil personnel, il copie ce chemin dans le presse-papiers :
> colle-le toi-même dans le champ ci-dessus (⌘V) et enregistre le profil.
> Un profil créé **plus tard** n'aura pas le suivi : relance simplement l'installeur
> (ElegooSlicer fermé), il n'ajoute rien en double.

## 2. Déclarer tes bobines

Ouvre une **nouvelle** fenêtre Terminal :

```
bobines ajouter --nom "PLA Noir Elegoo" --poids 1000 --prix 20 --tare 180 --emplacement 1
bobines ajouter --nom "PLA Blanc" --poids 1000 --reste 430 --emplacement 2
bobines liste
```

Ou double-clique sur `~/SuiviFilament/Bobines.command` dans le Finder (clic droit → Ouvrir
la première fois) : il affiche l'état des bobines et laisse le Terminal ouvert.

- `--poids` : poids net d'une bobine neuve (g)
- `--reste` : si la bobine est déjà entamée
- `--tare` : poids de la bobine vide (pour les pesées)
- `--emplacement` : numéro du filament dans le slicer (1 = premier ; 1 à 4 avec le Canvas)

## 3. Au quotidien

Rien à faire : à chaque **Exporter le G-code** ou **Envoyer à l'imprimante**, le script compte la
consommation, met à jour la bobine et note un résumé en commentaire en tête du G-code.
Une **alerte macOS** s'affiche si une bobine n'a pas assez de filament ou passe sous le seuil
(100 g par défaut). Un même G-code exporté deux fois n'est compté qu'une fois.

## 4. Commandes

| Commande | Effet |
|---|---|
| `bobines liste` | état des bobines (reste, %, valeur restante) |
| `bobines activer 3 --emplacement 1` | tu as changé la bobine de l'emplacement 1 |
| `bobines peser 3 --brut 612` | recale le reste avec une pesée (bobine + filament) |
| `bobines corriger 3 --reste 450` | fixe le reste à la main |
| `bobines annuler` | annule la dernière impression comptée |
| `bobines historique` | dernières impressions et total consommé |
| `bobines seuil 150` | seuil d'alerte « presque vide » |
| `bobines supprimer 3` | retire une bobine vide de la liste |

## Limites

- Comptage **à l'export**, pas en fin d'impression : impression ratée ou pas lancée → `bobines annuler`.
- Consommation = **estimation du slicer** ; une pesée de temps en temps (`peser`) recale tout.
- Avec le Canvas, l'emplacement = numéro du filament **dans le slicer**.
- Données : `~/SuiviFilament/bobines.json` (gardées si tu relances l'installeur).

## Désinstaller

ElegooSlicer fermé, dans le Terminal :
```
python3 ~/SuiviFilament/configurer_slicer.py --retirer ~/SuiviFilament/bobines
```
puis supprime le dossier `~/SuiviFilament` et les deux lignes « Suivi filament » à la fin de `~/.zshrc`.
