@echo off
chcp 65001 > nul
title Manga Translator Studio [PT-BR]
color 0A
echo =====================================================================
echo                MANGA TRANSLATOR STUDIO [PT-BR]
echo               Iniciando App com Interface Spotify...
echo =====================================================================
echo.
cd /d "C:\Users\ja329\OneDrive\Documentos\SISTEMA DE TRADUÇÃO"
start "" "C:\Users\ja329\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe" "C:\Users\ja329\OneDrive\Documentos\SISTEMA DE TRADUÇÃO\studio\server.py"
exit
