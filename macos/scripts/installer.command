#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installeur Suivi filament pour macOS — clic droit > Ouvrir la première fois.
set -e
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/SuiviFilament"
pause() { echo; read -n 1 -s -r -p "Appuie sur une touche pour fermer..."; echo; }

echo "=== Installation du suivi filament ==="

# 1) Trouver un Python 3 utilisable (Homebrew, python.org, puis celui d'Apple)
PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/bin/python3; do
  if [ -x "$c" ]; then
    if [ "$c" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then
      continue  # sans les outils Xcode, /usr/bin/python3 n'est qu'un raccourci d'installation
    fi
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then PY="$c"; break; fi
  fi
done
if [ -z "$PY" ]; then
  echo
  echo "Python 3 introuvable. Deux solutions :"
  echo "  - lancer :  xcode-select --install   (outils Apple, inclut Python 3)"
  echo "  - ou installer Python depuis https://www.python.org/downloads/macos/"
  echo "Puis relance installer.command."
  pause; exit 1
fi
echo "Python : $PY ($("$PY" --version))"

# 2) Copier les fichiers (les données bobines.json existantes sont conservées)
mkdir -p "$DEST"
cp "$SRC/suivi_filament.py" "$SRC/configurer_slicer.py" "$SRC/Bobines.command" "$DEST/"
sed "s|@PYTHON@|$PY|" "$SRC/bobines" > "$DEST/bobines"
chmod +x "$DEST/suivi_filament.py" "$DEST/bobines" "$DEST/Bobines.command"
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
echo "Fichiers installés dans : $DEST"

# 3) Commande « bobines » dans le Terminal
RC="$HOME/.zshrc"
if ! grep -q 'SuiviFilament' "$RC" 2>/dev/null; then
  printf '\n# Suivi filament\nexport PATH="$HOME/SuiviFilament:$PATH"\n' >> "$RC"
  echo "Commande « bobines » ajoutée au Terminal."
fi

# 4) Configuration automatique d'ElegooSlicer
CMD="$DEST/bobines"
case "$CMD" in *" "*) CMD="\"$DEST/bobines\"";; esac   # chemin avec espace : on le protège

echo
echo "=== Configuration d'ElegooSlicer ==="
while pgrep -if "ElegooSlicer.app/Contents/MacOS" >/dev/null 2>&1; do
  echo "ElegooSlicer est ouvert : enregistre ton travail et quitte-le (⌘Q),"
  read -r -p "puis appuie sur Entrée pour continuer (ou tape « passer » pour configurer à la main) : " rep
  [ "$rep" = "passer" ] && break
done

if [ "$rep" != "passer" ] && "$PY" "$DEST/configurer_slicer.py" "$CMD"; then
  echo
  echo "✔ ElegooSlicer est configuré. Au prochain export, la consommation sera comptée."
else
  printf '%s' "$CMD" | pbcopy
  echo
  echo "→ Configuration à la main : dans ElegooSlicer, onglet Process > mode Avancé > Autres >"
  echo "  Scripts de post-traitement, colle (⌘V, déjà dans le presse-papiers) :"
  echo
  echo "      $CMD"
  echo
  echo "  puis enregistre le profil (icône disquette)."
fi

echo
echo "Dernière étape : déclare ta bobine dans une NOUVELLE fenêtre Terminal, par exemple :"
echo "    bobines ajouter --nom \"PLA Noir Elegoo\" --poids 1000 --tare 180 --emplacement 1"
pause
