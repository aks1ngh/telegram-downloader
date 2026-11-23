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

echo.
echo Type: any = everything, or a mix like voice,photo,pdf
set /p KINDS=[voice,audio,photo,pdf,image]:
if "%KINDS%"=="" set "KINDS=voice,audio,photo,pdf,image"

python tg_media_export.py "%CHAT%" --types "%KINDS%" -o "%~dp0tg_media"
echo.
pause
