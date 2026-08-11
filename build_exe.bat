@echo off
REM ============================================================
REM  Construit BotRdvPermis.exe (application de bureau Windows)
REM  A executer UNE SEULE FOIS, sur un PC avec Python installe.
REM ============================================================

echo.
echo === Installation des dependances ===
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m playwright install chromium

echo.
echo === Construction de l'executable ===
python -m PyInstaller --onefile --windowed --noconfirm ^
    --name "BotRdvPermis" ^
    gui_app.py

REM config.yaml / cookies.json / bot.log restent des fichiers EXTERNES a cote
REM de l'exe (voir dist\) : ils ne sont pas figes dans l'executable, pour
REM pouvoir etre modifies par l'interface sans reconstruire l'app.
copy config.yaml dist\config.yaml >nul 2>&1

echo.
echo ============================================================
echo   Termine ! L'application se trouve dans :
echo   dist\BotRdvPermis.exe
echo.
echo   Copiez ce fichier .exe sur le Bureau de chaque poste.
echo   Le fichier config.yaml et cookies.json doivent rester
echo   dans le MEME dossier que l'exe (ou seront crees au 1er lancement).
echo ============================================================
pause
