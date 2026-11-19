@echo off
rem Windows : double-clic pour ouvrir l interface de Suivi Loyers.
cd /d "%~dp0"
py -3 src\serveur.py || python src\serveur.py
pause
