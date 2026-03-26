:: Install Python dependencies
pip install -r requirements.txt --force-reinstall

:: Set Launch.bat to run on startup
copy /Y "Launch.bat" "C:\Users\LattePanda\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup"

:: Install Chocolatey and FFmpeg
@"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -InputFormat None -ExecutionPolicy Bypass -Command " [System.Net.ServicePointManager]::SecurityProtocol = 3072; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))" && SET "PATH=%PATH%;%ALLUSERSPROFILE%\chocolatey\bin"
choco install ffmpeg

:: Clone the auxiliary repository
cd C:\Users\LattePanda\Documents\GitHub
git clone https://github.com/MekhyW/Eye-Graphics

:: Pause at the end
pause
