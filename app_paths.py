"""
app_paths.py - Onde ficam os arquivos do Manga Studio.

CODE_DIR: código e recursos que vêm com o programa (fontes, telas, modelos de fábrica).
DATA_DIR: dados do usuário (config.json, memória de traduções, regras, glossário, envios, caches,
          modelos baixados). Precisa ser gravável.

Rodando pelo código (PC com .bat, Colab): as duas são a pasta do projeto, como sempre foi.
No .exe (PyInstaller): CODE_DIR é a pasta interna do pacote e DATA_DIR é %APPDATA%\\MangaStudio.
A variável MANGA_STUDIO_DATA troca a pasta de dados nos dois casos.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import shutil
import sys

FROZEN = bool(getattr(sys, "frozen", False))
CODE_DIR = getattr(sys, "_MEIPASS", "") if FROZEN else os.path.dirname(os.path.abspath(__file__))

# Arquivos do usuário que uma instalação antiga (pasta do projeto) pode ter
USER_FILES = ("config.json", "memoria_traducoes.json", "aprendizado.txt", "glossary.json", "manga_reviews.json")
# Arquivos de fábrica copiados para a pasta de dados quando faltam
SEED_FILES = ("aprendizado.txt", "glossary.json")


def _default_data_dir():
    env = os.environ.get("MANGA_STUDIO_DATA", "").strip()
    if env:
        return os.path.abspath(os.path.expanduser(env))
    if not FROZEN:
        return CODE_DIR
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "MangaStudio")


DATA_DIR = _default_data_dir()
MODELS_DIR = os.path.join(DATA_DIR, "models")
LOG_DIR = os.path.join(DATA_DIR, "logs")


def data_path(*parts):
    return os.path.join(DATA_DIR, *parts)


def code_path(*parts):
    return os.path.join(CODE_DIR, *parts)


def legacy_dirs(exe_path=None, home=None):
    """Pastas de uma instalação antiga pelo código, de onde o .exe copia os dados na primeira execução."""
    exe_dir = os.path.dirname(os.path.abspath(exe_path or sys.executable))
    home = home or os.path.expanduser("~")
    cands = [exe_dir, os.path.dirname(exe_dir)]
    for docs in ("Documentos", "Documents", os.path.join("OneDrive", "Documentos"), os.path.join("OneDrive", "Documents")):
        for name in ("SISTEMA DE TRADUÇÃO", "SKILL-TRADUCAO-MANGA"):
            cands.append(os.path.join(home, docs, name))
    seen, found = set(), []
    for d in cands:
        key = os.path.normcase(os.path.abspath(d))
        if key in seen or key == os.path.normcase(os.path.abspath(DATA_DIR)):
            continue
        seen.add(key)
        if os.path.isfile(os.path.join(d, "auto_translate.py")):
            found.append(d)
    return found


def _copy_missing_tree(src, dst):
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        out_dir = os.path.join(dst, rel) if rel != "." else dst
        os.makedirs(out_dir, exist_ok=True)
        for name in files:
            target = os.path.join(out_dir, name)
            if not os.path.exists(target):
                shutil.copy2(os.path.join(root, name), target)


def prepare(log=None, exe_path=None, home=None):
    """Cria a pasta de dados e completa o que faltar. Nunca sobrescreve nada que já exista.
    Ordem: dados de uma instalação antiga -> arquivos de fábrica -> modelos de fábrica.
    Devolve a lista de arquivos copiados da instalação antiga."""
    if os.path.normcase(os.path.abspath(DATA_DIR)) == os.path.normcase(os.path.abspath(CODE_DIR)):
        return []
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    copied = []
    for src_dir in legacy_dirs(exe_path, home):
        for name in USER_FILES:
            src, dst = os.path.join(src_dir, name), os.path.join(DATA_DIR, name)
            if os.path.isfile(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
                copied.append(src)
    for name in SEED_FILES:
        src, dst = os.path.join(CODE_DIR, name), os.path.join(DATA_DIR, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
    if os.path.isdir(os.path.join(CODE_DIR, "models")):
        _copy_missing_tree(os.path.join(CODE_DIR, "models"), MODELS_DIR)
    if log and copied:
        log(f"[+] Dados da instalação antiga copiados para {DATA_DIR}: {', '.join(os.path.basename(c) for c in copied)}")
    return copied
