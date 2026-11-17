# Suivi filament pour ElegooSlicer

Petit module qui, **à chaque export ou envoi d'un G-code**, retire les grammes consommés du stock
de ta bobine, garde un historique et **t'alerte s'il ne reste pas assez de filament** pour l'impression.

Fonctionne aussi avec OrcaSlicer, Bambu Studio et PrusaSlicer (même mécanisme).

## 1. Installation (Windows)

1. Installe Python 3 depuis https://www.python.org/downloads/ (coche **« Add python.exe to PATH »**).
2. Crée un dossier, par exemple `C:\SuiviFilament\`, et copies-y `suivi_filament.py` et `bobines.bat`.
3. Dans **ElegooSlicer** :
   - onglet **Process** (Traitement) → active le mode **Avancé / Expert** (interrupteur en haut à droite) ;
   - section **Autres** → **Scripts de post-traitement** ;
   - colle cette ligne (adapte le chemin) :
     ```
     python "C:\SuiviFilament\suivi_filament.py";
     ```
   - enregistre le profil de traitement (icône disquette) pour que ce soit permanent.

> Sur macOS / Linux : `python3 "/chemin/vers/suivi_filament.py";`

## 2. Déclarer tes bobines

Ouvre un terminal dans le dossier (ou double-clique `bobines.bat` pour voir l'état et l'aide) :

```
bobines ajouter --nom "PLA Noir Elegoo" --poids 1000 --prix 20 --tare 180 --emplacement 1
bobines ajouter --nom "PLA Blanc" --poids 1000 --reste 430 --emplacement 2
bobines liste
```

- `--poids` : poids net d'une bobine neuve (g)
- `--reste` : si la bobine est déjà entamée
- `--tare` : poids de la bobine vide (pour les pesées)
- `--emplacement` : numéro du filament dans le slicer (1 = premier filament ; 1 à 4 avec le Canvas)

## 3. Au quotidien

Tu ne fais rien : à chaque **Exporter le G-code** ou **Envoyer à l'imprimante**, le script :

- lit la consommation dans le G-code ;
- la retire de la bobine active de chaque emplacement ;
- ajoute un résumé en commentaire au début du G-code (aucune commande modifiée) ;
- affiche une **fenêtre d'alerte** si une bobine n'a pas assez de filament, ou passe sous le seuil (100 g par défaut).

Un même G-code exporté deux fois n'est compté qu'une fois.

## 4. Commandes utiles

| Commande | Effet |
|---|---|
| `bobines liste` | état de toutes les bobines (reste, %, valeur restante) |
| `bobines activer 3 --emplacement 1` | tu as changé de bobine sur l'emplacement 1 |
| `bobines peser 3 --brut 612` | recale le reste avec une pesée (bobine + filament) |
| `bobines corriger 3 --reste 450` | fixe le reste à la main |
| `bobines annuler` | annule la dernière impression comptée (ratée, jamais lancée…) |
| `bobines historique` | dernières impressions et total consommé |
| `bobines seuil 150` | change le seuil d'alerte « presque vide » |
| `bobines supprimer 3` | retire une bobine vide de la liste |

## Limites à connaître

- Le comptage se fait **à l'export**, pas en fin d'impression : une impression annulée ou ratée
  est comptée en entier → utilise `bobines annuler`, ou recale avec `peser`.
- La consommation est **l'estimation du slicer** (très proche du réel, à quelques % près).
  Une pesée de temps en temps (`peser`) remet les compteurs à zéro.
- Avec le Canvas, l'emplacement = le numéro du filament **dans le slicer**. Si tu réaffectes les
  filaments à d'autres emplacements au moment de l'envoi, fais `activer` en conséquence.
- Les données sont dans `bobines.json`, à côté du script. Sauvegarde-le si tu y tiens.
