@echo off
chcp 65001 > nul
title Tradutor Automático de Mangás [PT-BR]
color 0A

echo =====================================================================
echo           TRADUTOR E DIAGRAMADOR DE MANGÁS [PT-BR]
echo   Destino Fixo: C:\Users\ja329\OneDrive\Documentos\MANGAS
echo =====================================================================
echo.

set "TARGET_DIR=%~1"

if "%TARGET_DIR%"=="" (
    echo Arraste a pasta do manga para dentro desta janela
    echo ou digite o caminho completo da pasta:
    echo.
    set /p "TARGET_DIR=>> Pasta do manga: "
)

:: Remove aspas que possam ter vindo com o arrastar e soltar
set TARGET_DIR=%TARGET_DIR:"=%

if "%TARGET_DIR%"=="" (
    echo.
    echo [ERRO] Nenhuma pasta foi selecionada.
    goto FIM
)

echo.
echo [*] Processando manga: "%TARGET_DIR%"
echo [*] Iniciando pipeline de OCR, traducao e diagramacao...
echo.

"C:\Users\ja329\AppData\Local\Python\bin\python.exe" "%~dp0auto_translate.py" "%TARGET_DIR%"

:FIM
echo.
echo =====================================================================
echo Processo finalizado! Pressione qualquer tecla para fechar esta janela.
echo =====================================================================
pause > nul
