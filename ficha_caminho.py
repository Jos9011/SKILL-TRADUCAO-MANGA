"""
ficha_caminho.py - Onde fica a Ficha da Obra (ficha_obra.json) de cada capítulo

Funciona com as pastas como o usuário já organiza, sem precisar reorganizar nada:

1. Pastas soltas, um capítulo por pasta (o caso mais comum):
     MANGAS/Toshiue no Kuro Gal Doukyuusei Ch.1
     MANGAS/Toshiue no Kuro Gal Doukyuusei Ch.2
   O nome da obra vem do nome da pasta sem o capítulo ("Ch.1", "Lesson 10", "Vol. 3",
   números soltos, tags como "[English]"). Todos os capítulos usam a mesma ficha em
   MANGAS/.fichas_obra/<nome da obra>.json
2. Obra com subpastas de capítulo (MANGAS/Obra/Cap 1): ficha em MANGAS/Obra/ficha_obra.json
3. Uma ficha_obra.json que já exista na pasta do capítulo ou na pasta pai continua valendo.

Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import unicodedata

FICHA_FILENAME = "ficha_obra.json"
FICHAS_DIR = ".fichas_obra"

_ROOT_NAMES = {"", "mangas", "mangas [pt-br]", "mydrive", "meu drive", "drive", "content"}
_CHAPTER_WORDS = (r"cap(?:[ií]tulo)?|ch(?:apter|ap)?|ep(?:is[oó]dio|isode)?|vol(?:ume)?|parte?|"
                  r"lesson|li[cç][aã]o|aula|chương")
_CHAPTER_RE = re.compile(
    r"(?i)(?:^|[\s_\-.\[(#])(?:" + _CHAPTER_WORDS + r"|第)[\s_\-.#]*\d|^\s*\d+(?:[.,]\d+)?\s*$"
)
_STRIP_CHAPTER_RE = re.compile(
    r"(?i)(?:\b(?:" + _CHAPTER_WORDS + r")\b\.?|#)\s*\d+(?:[.,]\d+)?(?:\s*[-~&,]\s*\d+(?:[.,]\d+)?)*"
)
_JP_CHAPTER_RE = re.compile(r"第\s*\d+\s*[話话章回巻卷]?")
_TAG_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】")
_NUMBER_RE = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?(?![\w])")


def looks_like_chapter(folder_name):
    return bool(_CHAPTER_RE.search(str(folder_name or "")))


def obra_title(folder_name):
    """'Toshiue no Kuro Gal Doukyuusei - OLDER BLACK GAL CLASSMATE Ch.1' -> sem o 'Ch.1'."""
    s = str(folder_name or "")
    s = _TAG_RE.sub(" ", s)
    s = _JP_CHAPTER_RE.sub(" ", s)
    s = _STRIP_CHAPTER_RE.sub(" ", s)
    s = _NUMBER_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(?:\s*[-_.,:~|]\s*)+$", "", s)
    s = re.sub(r"^(?:\s*[-_.,:~|]\s*)+", "", s)
    return s.strip()


def obra_key(folder_name):
    """Chave estável da obra: minúsculas, só letras/números, sem capítulo nem tags."""
    s = unicodedata.normalize("NFKC", obra_title(folder_name)).casefold()
    s = "".join(ch if unicodedata.category(ch)[0] in ("L", "N") else " " for ch in s)
    return re.sub(r"\s+", " ", s).strip()


def ficha_filename(folder_name):
    key = obra_key(folder_name)
    if not key:  # pasta só com número (ex: "015"): usa o nome normalizado da própria pasta
        key = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(folder_name or "obra")).casefold()).strip()
    key = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", key)[:100].strip(" .") or "obra"
    return key + ".json"


def _is_nested_chapter(chapter_name, parent_name):
    """Capítulo dentro da pasta da obra: o nome é só o capítulo ('Cap 1') ou repete o nome da pasta pai."""
    if parent_name.strip().lower() in _ROOT_NAMES or not looks_like_chapter(chapter_name):
        return False
    title_key = obra_key(chapter_name)
    parent_key = obra_key(parent_name)
    return not title_key or (bool(parent_key) and parent_key in title_key)


def resolve_ficha_path(manga_dir):
    """Escolhe o arquivo da ficha da obra a que este capítulo pertence."""
    d = os.path.abspath(str(manga_dir or "."))
    parent = os.path.dirname(d)
    base, parent_name = os.path.basename(d), os.path.basename(parent)
    local = os.path.join(d, FICHA_FILENAME)
    parent_f = os.path.join(parent, FICHA_FILENAME)
    if os.path.exists(local):
        return local
    if parent == d:
        return local
    if os.path.exists(parent_f) or _is_nested_chapter(base, parent_name):
        return parent_f
    return os.path.join(parent, FICHAS_DIR, ficha_filename(base))


def obra_display_name(manga_dir, ficha_path, fallback=""):
    """Nome da obra para gravar na ficha, conforme onde ela ficou."""
    d = os.path.abspath(str(manga_dir or "."))
    folder = os.path.dirname(os.path.abspath(ficha_path))
    if folder == d:
        return fallback or os.path.basename(d)
    if os.path.basename(folder) == FICHAS_DIR:
        return obra_title(os.path.basename(d)) or os.path.basename(d)
    return os.path.basename(folder) or fallback
