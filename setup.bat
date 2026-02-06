@echo off
echo ================================
echo  Polymarket Penny Bot - Setup
echo ================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python niet gevonden! Download op https://python.org/downloads
    echo Zorg dat je "Add to PATH" aanvinkt tijdens installatie.
    pause
    exit /b 1
)

echo [1/3] Dependencies installeren...
pip install -r requirements.txt
if errorlevel 1 (
    echo Installatie mislukt!
    pause
    exit /b 1
)

echo.
echo [2/3] Config aanmaken...
if not exist .env (
    copy .env.example .env
    echo .env aangemaakt — vul je API keys in!
) else (
    echo .env bestaat al, wordt niet overschreven.
)

echo.
echo [3/3] Klaar!
echo.
echo ================================
echo  Volgende stappen:
echo ================================
echo.
echo  1. Open .env in een tekstverwerker en vul in:
echo     - ANTHROPIC_API_KEY (voor AI research)
echo     - POLYMARKET_PRIVATE_KEY (alleen als je echt wil traden)
echo.
echo  2. Test met demo data:
echo     python bot.py --demo --scan
echo     python bot.py --demo --research
echo.
echo  3. Test met echte Polymarket data:
echo     python bot.py --scan
echo     python bot.py --research
echo.
pause
