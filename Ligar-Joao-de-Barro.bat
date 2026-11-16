@echo off
title Joao de Barro
set PATH=C:\Program Files\nodejs;%PATH%
set TELA=http://localhost:5177/assets-jdb/joaodebarro.html

rem Liga so o que estiver desligado: clicar no atalho de novo nao abre janelas repetidas
rem nem um segundo Coletor brigando com o primeiro.
curl -s -o nul --max-time 3 http://127.0.0.1:8866/api/avaliacao/coletor/status
if errorlevel 1 (
  echo Ligando o servidor... nao feche as janelas pretas que vao abrir
  start "JdB - Servidor" /min cmd /k "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn lovable.main:app --host 127.0.0.1 --port 8866"
  timeout /t 5 /nobreak >nul
)

curl -s -o nul --max-time 3 %TELA%
if errorlevel 1 (
  echo Ligando a tela...
  start "JdB - Tela" /min cmd /k "cd /d %~dp0frontend && npm run dev"
  timeout /t 6 /nobreak >nul
)

tasklist /v /fi "WINDOWTITLE eq JdB - Coletor*" | find /i "cmd.exe" >nul
if errorlevel 1 (
  echo Ligando o Coletor...
  start "JdB - Coletor" /min cmd /k "cd /d %~dp0coletor && .venv\Scripts\python.exe joaodebarro_coletor.py --servidor http://127.0.0.1:8866"
)

start "" "%TELA%"
exit
