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
echo ESCOLHA UMA OPCAO DE PROCESSAMENTO:
echo =====================================================================
echo [1] MOTOR ASIATICO (Mokuro)
echo     - Japones / Chines tradicional vertical
echo.
echo [2] MOTOR OCIDENTAL / UNIVERSAL (RapidOCR)
echo     - Ingles, Coreano, Espanhol, Scans, Webtoons
echo.
echo [3] LIMPAR CACHE E REFAZER TUDO DO ZERO (RapidOCR - Ingles/Universal)
echo     - Apaga OCR e traducoes antigas deste manga e refaz
echo.
echo [4] LIMPAR CACHE E REFAZER TUDO DO ZERO (Mokuro - Japones)
echo     - Apaga OCR e traducoes antigas deste manga e refaz
echo =====================================================================
set /p OCR_MODE=">> Digite 1, 2, 3 ou 4 (Padrao: 2): "

set OCR_FLAG=--rapidocr
set FORCE_FLAG=

if "%OCR_MODE%"=="1" (
    set OCR_FLAG=--mokuro
    set FORCE_FLAG=
)
if "%OCR_MODE%"=="2" (
    set OCR_FLAG=--rapidocr
    set FORCE_FLAG=
)
if "%OCR_MODE%"=="3" (
    set OCR_FLAG=--rapidocr
    set FORCE_FLAG=--force-ocr
)
if "%OCR_MODE%"=="4" (
    set OCR_FLAG=--mokuro
    set FORCE_FLAG=--force-ocr
)

echo.
echo [*] Iniciando processamento...
"C:\Users\ja329\AppData\Local\Python\bin\python.exe" "C:\Users\ja329\tools\manga-translator\auto_translate.py" "%TARGET_DIR%" %OCR_FLAG% %FORCE_FLAG%

:FIM
pause > nul
