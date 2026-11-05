@echo off
chcp 65001 > nul
title Tradutor de Mangas e Manhwas [PT-BR] - Qwen 2.5 / Dolphin
color 0A

echo =====================================================================
echo           TRADUTOR E DIAGRAMADOR DE MANGAS E MANHWAS [PT-BR]
echo               Motores de IA: Qwen 2.5 (CJK) / Dolphin 2.9
echo   Destino: C:\Users\ja329\OneDrive\Documentos\MANGAS
echo =====================================================================
echo.

set "TARGET_DIR=%~1"

if "%TARGET_DIR%"=="" (
    echo Arraste a pasta do manga ou manhwa para dentro desta janela:
    set /p "TARGET_DIR=>> "
)
set TARGET_DIR=%TARGET_DIR:"=%
if "%TARGET_DIR%"=="" goto FIM

echo.
echo =====================================================================
echo PASSO 1: MOTOR DE LEITURA (OCR)
echo =====================================================================
echo [1] AUTOMATICO INTELIGENTE (Detecta Coreano, Japones ou Ingles)
echo [2] JAPONES (Mokuro) - Mangas japoneses com leitura vertical
echo [3] COREANO / MANHWA (RapidOCR Hangul) - Manhwas e Webtoons Coreanos
echo [4] OCIDENTAL / UNIVERSAL (RapidOCR) - Ingles, Chines, etc.
echo [5] LIMPAR CACHE E REFAZER TUDO (Automatico)
echo [6] LIMPAR CACHE E REFAZER EM COREANO (Hangul)
echo [7] LIMPAR CACHE E REFAZER EM JAPONES (Mokuro)
echo =====================================================================
set /p OCR_MODE=">> Digite de 1 a 7 (Padrao: 1): "

set OCR_FLAG=
set FORCE_FLAG=

if "%OCR_MODE%"=="1" (
    set OCR_FLAG=
    set FORCE_FLAG=
)
if "%OCR_MODE%"=="2" (
    set OCR_FLAG=--mokuro
    set FORCE_FLAG=
)
if "%OCR_MODE%"=="3" (
    set OCR_FLAG=--korean
    set FORCE_FLAG=
)
if "%OCR_MODE%"=="4" (
    set OCR_FLAG=--rapidocr
    set FORCE_FLAG=
)
if "%OCR_MODE%"=="5" (
    set OCR_FLAG=
    set FORCE_FLAG=--force-ocr
)
if "%OCR_MODE%"=="6" (
    set OCR_FLAG=--korean
    set FORCE_FLAG=--force-ocr
)
if "%OCR_MODE%"=="7" (
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
echo [2] MANGA / MANHWA ADULTO +18 (Hentai, Erotico, Ecchi pesado)
echo     - Sem censura, girias explicitas e adaptacao adulta brasileira
echo =====================================================================
set /p CONTENT_MODE=">> Digite 1 ou 2 (Padrao: 2): "

set TYPE_FLAG=--adult
if "%CONTENT_MODE%"=="1" (
    set TYPE_FLAG=--normal
)

echo.
echo =====================================================================
echo PASSO 3: ONDE RODAR A IA (QWEN 2.5 / DOLPHIN SEM CENSURA)
echo =====================================================================
echo [1] AUTOMATICO (Segue a definicao do arquivo config.json)
echo [2] OPENROUTER NUVEM (100%% Nuvem - Nao usa recursos do PC)
echo [3] OLLAMA (Google Colab Nuvem, Servidor Remoto ou Local)
echo =====================================================================
set /p AI_MODE=">> Digite 1, 2 ou 3 (Padrao: 1): "

set AI_FLAG=
if "%AI_MODE%"=="2" set AI_FLAG=--openrouter
if "%AI_MODE%"=="3" set AI_FLAG=--ollama

echo.
echo [*] Iniciando processamento...
set "SCRIPT_PATH=%~dp0auto_translate.py"
if not exist "%SCRIPT_PATH%" set "SCRIPT_PATH=C:\Users\ja329\tools\manga-translator\auto_translate.py"
"C:\Users\ja329\AppData\Local\Python\bin\python.exe" "%SCRIPT_PATH%" "%TARGET_DIR%" %OCR_FLAG% %FORCE_FLAG% %TYPE_FLAG% %AI_FLAG%

:FIM
pause > nul
