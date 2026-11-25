"""
ficha_obra.py - Ficha da Obra (personagens, gêneros e termos fixos de um mangá)

Guarda em ficha_obra.json, na pasta da obra, o que precisa ficar IGUAL em todos os
capítulos: como cada personagem se chama em PT-BR, o gênero dele e os termos próprios
da obra. O Líder do capítulo (lider_capitulo.py) só ACRESCENTA novidades; nunca
sobrescreve o que já está na ficha. Divergências vão para "conflitos" para revisão
manual. O usuário pode editar o JSON à mão: a ficha manda.

- Onde fica: ver ficha_caminho.py. Com pastas soltas ("Obra Ch.1", "Obra Ch.2"), todos os
  capítulos usam .fichas_obra/<obra>.json na pasta que os contém.
- Desligar: "ficha_obra": false no config.json ou variável de ambiente MANGA_FICHA=0.
- Qualquer erro aqui é engolido: a ficha nunca pode quebrar a tradução.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import re
import shutil
import tempfile
import time
import unicodedata

from ficha_caminho import FICHA_FILENAME, looks_like_chapter, resolve_ficha_path  # noqa: F401 (reexportados)

FICHA_VERSION = 1
MAX_PERSONAGENS = 150
MAX_TERMOS = 300
MAX_CONFLITOS = 40
MAX_CAPITULOS = 1000
MAX_FIELD_LEN = 40
MAX_NOTA_LEN = 80
DEFAULT_PROMPT_MAX_CHARS = 900

_CJK_RE = re.compile(r'[぀-ヿ㐀-䶿一-鿿가-힯ᄀ-ᇿ㄰-㆏]')
_GENERO_MAP = {
    "m": "M", "masc": "M", "masculino": "M", "male": "M", "homem": "M", "h": "M", "menino": "M",
    "f": "F", "fem": "F", "feminino": "F", "female": "F", "mulher": "F", "menina": "F",
}


def is_enabled(config=None):
    """Liga/desliga pela variável MANGA_FICHA (0/1) ou pelo config ("ficha_obra")."""
    env = os.environ.get("MANGA_FICHA", "").strip().lower()
    if env in ("0", "false", "off", "nao", "não"):
        return False
    if env in ("1", "true", "on", "sim"):
        return True
    if isinstance(config, dict) and config.get("ficha_obra") is not None:
        return bool(config.get("ficha_obra"))
    return True


def normalize_key(text):
    """NFKC + minúsculas + pontuação vira espaço. Usado para comparar nomes e achar menções."""
    s = unicodedata.normalize("NFKC", str(text or "")).casefold()
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        out.append(ch if cat[0] in ("L", "N", "M") else " ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def mentions(key, norm_text):
    """True se o termo normalizado aparece no texto normalizado (palavra inteira fora do CJK)."""
    if not key or not norm_text:
        return False
    if _CJK_RE.search(key):
        return key in norm_text
    return f" {key} " in f" {norm_text} "


# ---------------------------------------------------------------------------
# Arquivo: ler e salvar (onde fica: ficha_caminho.py)
# ---------------------------------------------------------------------------
def empty_ficha(obra=""):
    return {"versao": FICHA_VERSION, "obra": str(obra or ""), "atualizado_em": "",
            "capitulos_lidos": [], "personagens": [], "termos": [], "conflitos": []}


def _clean_text(value, max_len):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_len].strip()

def clean_genero(value):
    s = str(value or "").strip().lower()
    return _GENERO_MAP.get(s, "M" if s.startswith("masc") else "F" if s.startswith("fem") else "?")


def clean_personagem(item):
    if not isinstance(item, dict):
        return None
    orig = _clean_text(item.get("original"), MAX_FIELD_LEN)
    pt = _clean_text(item.get("pt") or item.get("nome_pt") or orig, MAX_FIELD_LEN)
    if not orig or not normalize_key(orig):
        return None
    return {"original": orig, "pt": pt, "genero": clean_genero(item.get("genero")),
            "nota": _clean_text(item.get("nota"), MAX_NOTA_LEN)}


def clean_termo(item):
    if not isinstance(item, dict):
        return None
    orig = _clean_text(item.get("original"), MAX_FIELD_LEN)
    pt = _clean_text(item.get("pt"), MAX_FIELD_LEN)
    if not orig or not pt or not normalize_key(orig):
        return None
    return {"original": orig, "pt": pt, "nota": _clean_text(item.get("nota"), MAX_NOTA_LEN)}


def load_ficha(path, obra=""):
    """Lê a ficha. Se o arquivo estiver corrompido, guarda uma cópia .bak e começa uma vazia."""
    ficha = empty_ficha(obra)
    if not path or not os.path.exists(path):
        return ficha
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("ficha não é um objeto JSON")
    except Exception as e:
        try:
            shutil.copy2(path, path + ".corrompido.bak")
        except Exception:
            pass
        print(f"[!] [Ficha] {os.path.basename(path)} ilegível ({e}); cópia salva em .corrompido.bak")
        return ficha
    ficha["obra"] = str(data.get("obra") or obra or "")
    ficha["atualizado_em"] = str(data.get("atualizado_em") or "")
    ficha["capitulos_lidos"] = [str(c) for c in (data.get("capitulos_lidos") or []) if str(c).strip()]
    ficha["personagens"] = [p for p in map(clean_personagem, data.get("personagens") or []) if p]
    ficha["termos"] = [t for t in map(clean_termo, data.get("termos") or []) if t]
    ficha["conflitos"] = [c for c in (data.get("conflitos") or []) if isinstance(c, (str, dict))]
    return ficha


def save_ficha(ficha, path):
    """Grava de forma atômica (arquivo temporário + replace) para não corromper no meio."""
    try:
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        ficha["atualizado_em"] = time.strftime("%Y-%m-%d %H:%M:%S")
        fd, tmp = tempfile.mkstemp(prefix=".ficha_", suffix=".tmp", dir=folder)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ficha, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[!] [Ficha] Não foi possível salvar {path}: {e}")
        return False


# ---------------------------------------------------------------------------
# Mesclar novidades do Líder (só acrescenta; nunca sobrescreve)
# ---------------------------------------------------------------------------
def _add_conflito(ficha, texto, capitulo):
    lista = ficha.setdefault("conflitos", [])
    if any(texto in str(c) for c in lista):
        return False
    lista.append(f"[{capitulo}] {texto}" if capitulo else texto)
    del lista[:-MAX_CONFLITOS]
    return True


def _find_personagem(pers_idx, key):
    """Mesmo personagem: nome igual ou um contido no outro por palavras ('MANABU' e 'MANABU TOKITO')."""
    if key in pers_idx:
        return pers_idx[key]
    words = set(key.split())
    if not words or _CJK_RE.search(key):
        return None
    for k, p in pers_idx.items():
        kw = set(k.split())
        if kw and not _CJK_RE.search(k) and (words <= kw or kw <= words):
            return p
    return None


def merge_novidades(ficha, novidades, capitulo=""):
    """Acrescenta personagens/termos novos; completa gênero '?'; registra divergências."""
    report = {"personagens_novos": [], "termos_novos": [], "generos_completados": [], "conflitos": []}
    if not isinstance(novidades, dict):
        return report

    def conflito(msg):
        if _add_conflito(ficha, msg, capitulo):
            report["conflitos"].append(msg)

    pers_idx = {normalize_key(p["original"]): p for p in ficha.setdefault("personagens", [])}
    for item in novidades.get("personagens") or []:
        new = clean_personagem(item)
        if not new:
            continue
        cur = _find_personagem(pers_idx, normalize_key(new["original"]))
        if cur is None:
            if len(ficha["personagens"]) < MAX_PERSONAGENS:
                ficha["personagens"].append(new)
                pers_idx[normalize_key(new["original"])] = new
                report["personagens_novos"].append(new["original"])
            continue
        if cur.get("genero", "?") == "?" and new["genero"] != "?":
            cur["genero"] = new["genero"]
            report["generos_completados"].append(cur["original"])
        elif new["genero"] != "?" and cur.get("genero") != new["genero"]:
            conflito(f"{cur['original']}: ficha diz gênero {cur['genero']}, capítulo sugere {new['genero']}")
        if new["pt"] and normalize_key(new["pt"]) != normalize_key(cur.get("pt")):
            conflito(f"{cur['original']}: ficha usa '{cur.get('pt')}', capítulo sugere '{new['pt']}'")
        if not cur.get("nota") and new.get("nota"):
            cur["nota"] = new["nota"]

    termo_idx = {normalize_key(t["original"]): t for t in ficha.setdefault("termos", [])}
    for item in novidades.get("termos") or []:
        new = clean_termo(item)
        if not new:
            continue
        key = normalize_key(new["original"])
        if key in pers_idx:
            continue  # já é personagem; não duplicar como termo
        cur = termo_idx.get(key)
        if cur is None:
            if len(ficha["termos"]) < MAX_TERMOS:
                ficha["termos"].append(new)
                termo_idx[key] = new
                report["termos_novos"].append(new["original"])
        elif normalize_key(new["pt"]) != normalize_key(cur.get("pt")):
            conflito(f"{cur['original']}: ficha usa '{cur.get('pt')}', capítulo sugere '{new['pt']}'")
    return report


def chapter_already_read(ficha, capitulo):
    return bool(capitulo) and str(capitulo) in (ficha.get("capitulos_lidos") or [])

def mark_chapter_read(ficha, capitulo):
    lidos = ficha.setdefault("capitulos_lidos", [])
    if capitulo and str(capitulo) not in lidos:
        lidos.append(str(capitulo))
        del lidos[:-MAX_CAPITULOS]


# ---------------------------------------------------------------------------
# Texto para os prompts
# ---------------------------------------------------------------------------
_GENERO_LABEL = {"M": "homem", "F": "mulher"}


def _personagem_line(p):
    gen = _GENERO_LABEL.get(p.get("genero"))
    line = f"- {p['original']} -> {p.get('pt') or p['original']}"
    if gen:
        line += f" ({gen})"
    if p.get("nota"):
        line += f": {p['nota']}"
    return line + "\n"


def build_prompt_block(ficha, texts=None, max_chars=DEFAULT_PROMPT_MAX_CHARS):
    """
    Bloco para o prompt do Agente 2. Primeiro o que aparece nos balões do lote,
    depois o resto da ficha até o limite de caracteres. "" se não houver nada.
    """
    try:
        if not ficha:
            return ""
        norm_text = normalize_key(" \n ".join(str(t or "") for t in (texts or [])))
        pers = ficha.get("personagens") or []
        terms = ficha.get("termos") or []

        def relevant(entry):
            return mentions(normalize_key(entry.get("original")), norm_text)

        ordered = ([_personagem_line(p) for p in pers if relevant(p)]
                   + [f"- {t['original']} -> {t['pt']}\n" for t in terms if relevant(t)]
                   + [_personagem_line(p) for p in pers if not relevant(p)]
                   + [f"- {t['original']} -> {t['pt']}\n" for t in terms if not relevant(t)])
        if not ordered:
            return ""
        header = ("\nFICHA DA OBRA (nomes, gêneros e termos FIXOS desta obra; use sempre estes nomes "
                  "e concorde pronomes/adjetivos com o gênero indicado):\n")
        lines, total = [], len(header)
        for line in ordered:
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return header + "".join(lines) if lines else ""
    except Exception:
        return ""

