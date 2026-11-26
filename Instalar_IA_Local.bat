@echo off
chcp 65001 > nul
title Manga Studio - Instalar IA local
echo =====================================================================
echo   MANGA STUDIO - Instalando a IA local (Ollama) neste PC
echo   O modelo e escolhido pela sua placa de video. Pode levar alguns
echo   minutos (o modelo tem alguns GB). Nao feche esta janela.
echo =====================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_ia_local.ps1" %*
echo.
if errorlevel 1 (
  echo Algo deu errado. Leia a mensagem acima e tente de novo.
) else (
  echo Tudo certo. Pode abrir o Manga Studio.
)
pause
