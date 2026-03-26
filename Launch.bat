@echo off

:: Update the "Eye-Graphics" repository
cd "C:\Users\LattePanda\Documents\GitHub\Eye-Graphics"
git pull || echo Git pull failed
cd "..\"

:: Update the "DYNAMO-Electronic_Fursuit-3.0" repository
cd "DYNAMO-Electronic_Fursuit-3.0"
git pull || echo Git pull failed

:: Minimize the command prompt window
powershell -window minimized -command ""

:: Start Eye-Graphics.exe
start "" "C:\Users\LattePanda\Documents\GitHub\Eye-Graphics\Build\Eye-Graphics.exe" || echo Eye-Graphics crashed

:: Start DYNAMO.py
cd "src"
python DYNAMO-2.py || echo DYNAMO-2.py crashed

:: Pause at the end
pause
