#!/bin/bash
# macOS / Linux : double-clic pour ouvrir l'interface de Suivi Loyers.
cd "$(dirname "$0")" && exec python3 src/serveur.py
