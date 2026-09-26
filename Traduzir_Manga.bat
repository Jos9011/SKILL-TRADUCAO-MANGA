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
echo PASSO 1: MOTOR DE LEITURA (OCR)
echo =====================================================================
echo [1] MOTOR ASIATICO (Mokuro) - Japones / Chines tradicional vertical
echo [2] MOTOR OCIDENTAL / UNIVERSAL (RapidOCR) - Ingles, Coreano, etc.
echo [3] LIMPAR CACHE E REFAZER TUDO (RapidOCR - Ingles/Universal)
echo [4] LIMPAR CACHE E REFAZER TUDO (Mokuro - Japones)
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
echo =====================================================================
echo PASSO 2: ESTILO DE CONTEUDO E TRADUCAO
echo =====================================================================
echo [1] MANGA NORMAL / PADRAO (Acao, Aventura, Shounen, Romance, Isekai)
echo     - Traducao fiel e fluida, sem vulgaridade desnecessaria
echo.
echo [2] MANGA ADULTO / +18 (Hentai, Erotico, Ecchi pesado)
echo     - Sem censura, girias explicitas e adaptacao adulta brasileira
echo =====================================================================
set /p CONTENT_MODE=">> Digite 1 ou 2 (Padrao: 1): "

set TYPE_FLAG=--normal
if "%CONTENT_MODE%"=="2" (
    set TYPE_FLAG=--adult
)

echo.
echo [*] Iniciando processamento...
set "SCRIPT_PATH=%~dp0auto_translate.py"
if not exist "%SCRIPT_PATH%" set "SCRIPT_PATH=C:\Users\ja329\tools\manga-translator\auto_translate.py"
"C:\Users\ja329\AppData\Local\Python\bin\python.exe" "%SCRIPT_PATH%" "%TARGET_DIR%" %OCR_FLAG% %FORCE_FLAG% %TYPE_FLAG%

:FIM
pause > nul
