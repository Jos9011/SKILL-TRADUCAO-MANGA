@echo off
chcp 65001 > nul
title Tradutor de Mangas [PT-BR]
color 0A

echo =====================================================================
echo           TRADUTOR E DIAGRAMADOR DE MANGAS [PT-BR]
echo   Destino: C:\Users\ja329\OneDrive\Documentos\MANGAS
echo =====================================================================
echo.

set "TARGET_DIR=%~1"

if "%TARGET_DIR%"=="" (
    echo Arraste a pasta do manga para dentro desta janela:
    set /p "TARGET_DIR=>> "
)
set TARGET_DIR=%TARGET_DIR:"=%
if "%TARGET_DIR%"=="" goto FIM

echo.
echo =====================================================================
echo ESCOLHA O MOTOR DE LEITURA (OCR) PARA ESTE MANGA:
echo =====================================================================
echo [1] MOTOR ASIATICO (Mokuro)
echo     - Especializado em Japones/Chines vertical. Melhor qualidade.
echo     - Nao recomendado para ingles.
echo.
echo [2] MOTOR OCIDENTAL / UNIVERSAL (RapidOCR)
echo     - Le qualquer idioma (Ingles, Espanhol, Coreano, etc).
echo     - Ideal para Scans e Webtoons.
echo =====================================================================
set /p OCR_MODE=">> Digite 1 ou 2 (Padrao: 2): "

if "%OCR_MODE%"=="1" (
    set OCR_FLAG=--mokuro
) else (
    set OCR_FLAG=--rapidocr
)

echo.
echo [*] Iniciando processamento...
"C:\Users\ja329\AppData\Local\Python\bin\python.exe" "C:\Users\ja329\tools\manga-translator\auto_translate.py" "%TARGET_DIR%" %OCR_FLAG%

:FIM
pause > nul
