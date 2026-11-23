@echo off
setlocal
cd /d "%~dp0"

if not exist config.json (
  echo Missing config.json.
  echo Copy config.example.json to config.json and fill in api_id / api_hash
  echo from https://my.telegram.org
  pause
  exit /b 1
)

if "%~1"=="" (
  set /p CHAT=Channel (@name, t.me link, or -100... id):
) else (
  set "CHAT=%~1"
)

python tg_audio_export.py "%CHAT%" -o "%~dp0tg_audio" %2 %3 %4 %5
echo.
pause
