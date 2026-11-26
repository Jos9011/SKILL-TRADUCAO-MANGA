"""
manga_studio_app.py - Ponto de entrada do Manga Studio para Windows (.exe feito com PyInstaller).

  MangaStudio.exe                -> prepara a pasta de dados, sobe o servidor e abre a janela do app
  MangaStudio.exe --pick-folder  -> só abre o seletor de pastas do Windows e imprime a escolha
                                    (o servidor chama assim, porque no .exe não existe "python -c")
  MangaStudio.exe --self-test    -> confere bibliotecas e arquivos do pacote e sai (usado no GitHub Actions)

Também funciona pelo código: python manga_studio_app.py
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
for extra in (HERE, os.path.join(HERE, "studio")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import app_paths  # noqa: E402


def pick_folder(title="Selecione a Pasta", init_dir=""):
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    chosen = filedialog.askdirectory(title=title, initialdir=init_dir or None)
    root.destroy()
    return chosen or ""


def _redirect_output():
    """Sem console (janela do app), print e tqdm iriam para lugar nenhum: grava em logs/manga_studio.log."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    os.makedirs(app_paths.LOG_DIR, exist_ok=True)
    log = open(os.path.join(app_paths.LOG_DIR, "manga_studio.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or log
    sys.stderr = sys.stderr or log
    return log


def self_test():
    """Importa tudo que a tradução usa e confere os arquivos do pacote. Código de saída 0 = ok."""
    problems = []
    for mod in ("cv2", "numpy", "PIL", "flask", "onnxruntime", "rapidocr_onnxruntime", "pyphen", "wordninja",
                "deep_translator", "requests", "fitz", "psutil", "pyclipper", "tkinter",
                "auto_translate", "balloon_assign", "balloon_color", "typography_ptbr", "ocr_text_fix",
                "ficha_obra", "lider_capitulo", "manga_colorizer", "server"):
        try:
            __import__(mod)
        except Exception as e:  # noqa: BLE001 - queremos listar todos os problemas
            problems.append(f"import {mod}: {e}")
    for rel in ("studio/templates/index.html", "studio/static/css/base.css", "studio/static/js/core.js",
                "studio/static/fonts/animeace2_reg.ttf", "fonts/animeace2_reg.ttf", "aprendizado.txt", "glossary.json"):
        if not os.path.isfile(app_paths.code_path(*rel.split("/"))):
            problems.append(f"arquivo ausente no pacote: {rel}")
    try:
        import pyphen
        pyphen.Pyphen(lang="pt_BR")
        import wordninja
        assert wordninja.split("derekanderson") == ["derek", "anderson"]
        from rapidocr_onnxruntime import RapidOCR
        RapidOCR()
        import server
        client = server.app.test_client()
        page = client.get("/")
        if page.status_code != 200 or b"Solte o cap" not in page.data:
            problems.append(f"página inicial respondeu {page.status_code}")
        if client.get("/static/js/core.js").status_code != 200:
            problems.append("arquivos estáticos não são servidos")
    except Exception:
        problems.append(traceback.format_exc())
    print("SELF-TEST", "OK" if not problems else "FALHOU")
    for p in problems:
        print(" -", p)
    print("Dados em:", app_paths.DATA_DIR)
    return 0 if not problems else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--pick-folder":
        title = argv[1] if len(argv) > 1 else "Selecione a Pasta"
        init_dir = argv[2] if len(argv) > 2 else ""
        chosen = pick_folder(title, init_dir)
        if len(argv) > 3:
            with open(argv[3], "w", encoding="utf-8") as f:
                f.write(chosen)
        elif sys.stdout is not None:
            print(chosen)
        return 0
    _redirect_output()
    app_paths.prepare(log=print)
    if argv and argv[0] == "--self-test":
        return self_test()
    try:
        import server
        server.run_desktop(5050)
        return 0
    except Exception:
        with open(os.path.join(app_paths.DATA_DIR, "crash.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise


if __name__ == "__main__":
    sys.exit(main())
