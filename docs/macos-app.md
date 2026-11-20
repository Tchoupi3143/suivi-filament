# Suivi Filament — application Mac

Gère tes bobines et compte automatiquement le filament de chaque impression envoyée
depuis ElegooSlicer.

## Installer

1. Dézippe, puis glisse **Suivi Filament.app** dans le dossier **Applications**.
2. Premier lancement : **clic droit sur l'app → Ouvrir → Ouvrir**
   (l'app n'est pas signée par Apple, macOS demande une confirmation une seule fois).
   - Si macOS dit que l'app est « endommagée », ouvre le Terminal et tape :
     ```
     xattr -cr "/Applications/Suivi Filament.app"
     ```
     puis relance-la.
   - S'il manque Python, l'app propose d'installer les outils gratuits d'Apple.
3. L'interface s'ouvre dans ton navigateur.

## Activer la détection automatique (une seule fois)

Dans l'app, clique sur **Activer la détection** : le bandeau passe au vert.
C'est tout — rien à régler dans ElegooSlicer.

Ensuite, chaque impression **envoyée** depuis ElegooSlicer, et chaque G-code **exporté** dans
Téléchargements ou sur le Bureau, est compté sur la bobine chargée en « Filament 1 », « Filament 2 »…
Une notification confirme le comptage, et une alerte s'affiche s'il ne reste pas assez de filament.
La détection tourne en arrière-plan, même app fermée, et ne peut pas bloquer une impression.

Si tu avais relié une ancienne version via les « Scripts de post-traitement », l'app propose de
retirer ce réglage (ElegooSlicer doit être fermé).

## Au quotidien

- **Ajouter une bobine** : onglet **Catalogue Elegoo** → choisis la gamme (PLA RFID, PLA Matte,
  PETG HF…), la couleur et le format acheté (bobine 1 kg, lot 5 ou 10 kg, grosse bobine 3 ou 5 kg).
  Nom, matière, couleur, poids et **prix au kg** sont remplis tout seuls avec les prix de la boutique
  Elegoo Europe. Pour une autre marque, onglet **Autre marque** (saisie libre).
- **Prix Elegoo** : mis à jour automatiquement une fois par semaine au lancement de l'app
  (ou bouton **Actualiser les prix**). Sans connexion, les derniers prix connus sont utilisés.
  Le prix d'une bobine déjà enregistrée ne change pas : c'est ce que tu l'as payée.
- **Menu Filament 1 à 4 / Rangée** : indique quelle bobine est chargée sur la machine.
- **Peser** : pose la bobine sur une balance, l'app recalcule le reste exact.
- **Annuler la dernière** : pour une impression ratée ou jamais lancée (le filament est rendu).
- **Quitter**, ou ferme simplement l'onglet : l'app s'arrête toute seule.
  Le comptage dans ElegooSlicer continue même quand l'app est fermée.

## Bon à savoir

- Données : `~/SuiviFilament/bobines.json` (dans ton dossier personnel), catalogue : `~/SuiviFilament/catalogue_elegoo.json`.
- Comptage au moment de l'export (estimation du slicer), pas en fin d'impression.
- Tout reste sur ton Mac : l'interface n'est accessible que depuis ton ordinateur.
