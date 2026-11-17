#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Double-clic dans le Finder : affiche l'état des bobines puis laisse le Terminal ouvert pour taper des commandes.
cd "$(dirname "$0")"
./bobines liste
echo
echo "Commandes : ./bobines ajouter | activer | peser | corriger | annuler | historique | seuil | supprimer"
echo "Aide :      ./bobines --help"
echo
exec "$SHELL" -l
