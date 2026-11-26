# -*- mode: python ; coding: utf-8 -*-
# manga_studio.spec - Receita do PyInstaller para o MangaStudio.exe (pasta com o .exe, não arquivo único:
# abre mais rápido e é menos barrado por antivírus). Montar: pyinstaller manga_studio.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("studio/templates", "studio/templates"),
    ("studio/static", "studio/static"),
    ("fonts", "fonts"),
    ("models", "models"),
    ("aprendizado.txt", "."),
    ("glossary.json", "."),
    ("config.example.json", "."),
]
for pkg in ("rapidocr_onnxruntime", "pyphen"):
    datas += collect_data_files(pkg)
# wordninja é um módulo solto (não pacote): a lista de palavras fica em <site-packages>/wordninja/
import os
import wordninja
datas.append((os.path.join(os.path.dirname(wordninja.__file__), "wordninja", "wordninja_words.txt.gz"), "wordninja"))

hiddenimports = [
    "server", "drive_helper", "job_control", "app_launcher",
    "auto_translate", "balloon_assign", "balloon_cavity", "balloon_color", "typography_ptbr",
    "ocr_text_fix", "ficha_obra", "ficha_caminho", "lider_capitulo", "rag_memory", "dialogue_chunk_mapper",
    "manga_colorizer", "color_merge", "color_reference", "dataset_exporter", "version", "app_paths",
    "ollama_client", "gemini_text", "quota_wait", "chapter_context", "chapter_translator",
    "tkinter", "tkinter.filedialog", "fitz", "pymupdf",
]
hiddenimports += collect_submodules("plyer.platforms.win")

# RapidOCR 1.2.x põe a própria pasta no sys.path e importa "ch_ppocr_v3_det" etc. como módulos soltos
import rapidocr_onnxruntime
RAPID_DIR = os.path.dirname(rapidocr_onnxruntime.__file__)
for sub in sorted(os.listdir(RAPID_DIR)):
    sub_dir = os.path.join(RAPID_DIR, sub)
    if sub.startswith("ch_ppocr") and os.path.isdir(sub_dir):
        hiddenimports.append(sub)
        hiddenimports += [f"{sub}.{f[:-3]}" for f in os.listdir(sub_dir) if f.endswith(".py") and f != "__init__.py"]

a = Analysis(
    ["manga_studio_app.py"],
    pathex=[".", "studio", RAPID_DIR],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "torchvision", "tensorflow", "matplotlib", "gradio", "mokuro", "manga_ocr",
              "transformers", "scipy", "pandas", "IPython", "notebook", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MangaStudio",
    icon="studio/static/favicon.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="MangaStudio", upx=False)
