@echo off
echo Polymarket Penny Bot
echo =====================
echo.
echo  1 = Demo scan (nep data)
echo  2 = Demo AI research (nep data)
echo  3 = Demo full cycle (nep data)
echo  4 = Echte scan (Polymarket live)
echo  5 = Echte AI research (Polymarket live)
echo  6 = Musk tweet strategie (preview)
echo  7 = Portfolio bekijken
echo  0 = Afsluiten
echo.
set /p keuze="Keuze: "

if "%keuze%"=="1" python bot.py --demo --scan
if "%keuze%"=="2" python bot.py --demo --research
if "%keuze%"=="3" python bot.py --demo --once
if "%keuze%"=="4" python bot.py --scan
if "%keuze%"=="5" python bot.py --research
if "%keuze%"=="6" python bot.py --musk --dry
if "%keuze%"=="7" python -c "from trader import Trader; from config import Config; t=Trader(config=Config(),client=None); print(t.get_summary())"
if "%keuze%"=="0" exit /b 0

echo.
pause
