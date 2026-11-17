@echo off
REM SPDX-License-Identifier: GPL-3.0-or-later
REM Raccourci : bobines liste / bobines ajouter --nom "PLA Noir" --poids 1000 --emplacement 1 ...
if "%~1"=="" (
  python "%~dp0suivi_filament.py" liste
  echo.
  python "%~dp0suivi_filament.py" --help
  pause
) else (
  python "%~dp0suivi_filament.py" %*
)
