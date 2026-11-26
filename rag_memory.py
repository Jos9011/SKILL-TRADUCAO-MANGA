"""
rag_memory.py - Memória de Tradução por Semelhança (RAG leve, sem dependências)
Recupera traduções antigas PARECIDAS (não só idênticas) de memoria_traducoes.json
e as injeta no prompt como exemplos, para manter termos e tom consistentes.

- Busca BM25 sobre n-gramas de caracteres: funciona com chinês/japonês/coreano,
  tolera ruído de OCR e roda em Python puro (PC, Google Colab e Android/Chaquopy).
- O índice vive só na memória e é refeito quando o JSON muda (nada extra a salvar).
- Qualquer erro aqui é engolido: o RAG nunca pode quebrar a tradução.
- Desligar: "rag_memory": false no config.json ou variável de ambiente MANGA_RAG=0.

Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import math
import os
import re
import unicodedata
from collections import Counter

import app_paths

SCRIPT_DIR = app_paths.DATA_DIR
DEFAULT_MEMORY_PATH = os.path.join(SCRIPT_DIR, "memoria_traducoes.json")
_CONFIG_PATHS = (
    "/content/drive/MyDrive/.manga_studio/config.json",
    os.path.join(SCRIPT_DIR, "config.json"),
)

_CJK_RE = re.compile(r'[぀-ヿ㐀-䶿一-鿿가-힯ᄀ-ᇿ㄰-㆏]')
_WORD_RE = re.compile(r"[a-z0-9à-öø-ÿ']+")
_BAD_TRANSLATION_MARKERS = ("<x ", "MYMEMORY")

# Limites pensados para a cota TPM do Groq: poucos exemplos, curtos.
DEFAULT_TOP_K_PER_TEXT = 3
DEFAULT_MAX_EXAMPLES = 8
DEFAULT_MAX_CHARS = 900
DEFAULT_MIN_SCORE = 0.35   # fração mínima de n-gramas da consulta presentes no exemplo
MAX_EXAMPLE_LEN = 160


def normalize_text(text):
    """NFKC + minúsculas + remove pontuação/símbolos (～♡：!? etc.) e espaços extras."""
    s = unicodedata.normalize("NFKC", str(text or "")).lower()
    out = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "N"):
            out.append(ch)
        elif ch.isspace() or cat[0] in ("P", "S", "Z"):
            out.append(" ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def tokenize(text):
    """
    Gera termos para busca:
      - CJK: unigramas + bigramas de caracteres (sem espaços entre palavras nesses idiomas)
      - Latino: palavras inteiras + trigramas de caracteres (tolera erro de OCR)
    """
    norm = normalize_text(text)
    if not norm:
        return []
    terms = []
    cjk_chars = [c for c in norm if _CJK_RE.match(c)]
    if cjk_chars:
        for run in re.findall(_CJK_RE.pattern + "+", norm):
            terms.extend(run)
            terms.extend(run[i:i + 2] for i in range(len(run) - 1))
    for word in _WORD_RE.findall(norm):
        terms.append("w:" + word)
        padded = f"#{word}#"
        if len(padded) > 3:
            terms.extend("t:" + padded[i:i + 3] for i in range(len(padded) - 2))
    return terms


class TranslationMemoryIndex:
    """Índice BM25 em memória sobre pares (original -> tradução)."""

    def __init__(self, pairs, k1=1.5, b=0.75):
        self.k1 = k1
        self.b = b
        self.docs = []      # (orig, trans, Counter(termos), tamanho)
        self.df = Counter()
        for orig, trans in pairs:
            o_s, t_s = str(orig or "").strip(), str(trans or "").strip()
            if not o_s or not t_s or o_s == t_s:
                continue
            if any(m.upper() in t_s.upper() for m in _BAD_TRANSLATION_MARKERS):
                continue
            tf = Counter(tokenize(o_s))
            if not tf:
                continue
            self.docs.append((o_s, t_s, tf, sum(tf.values())))
            self.df.update(tf.keys())
        n = len(self.docs)
        self.avg_len = (sum(d[3] for d in self.docs) / n) if n else 0.0
        self.idf = {t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in self.df.items()}

    def __len__(self):
        return len(self.docs)

    def search(self, query, top_k=DEFAULT_TOP_K_PER_TEXT, min_score=DEFAULT_MIN_SCORE):
        """Retorna [(orig, trans, cobertura)] dos exemplos mais parecidos com a consulta."""
        q_terms = set(tokenize(query))
        if not q_terms or not self.docs:
            return []
        # Termo nunca visto na memória = o mais raro possível (peso máximo), não zero.
        # Sem isso "晚安" (boa noite) casaria 100% com "早安" (bom dia) só pelo "安".
        unseen_idf = math.log(1 + (len(self.docs) + 0.5) / 0.5)
        q_weight = sum(self.idf.get(t, unseen_idf) for t in q_terms) or 1.0
        scored = []
        for orig, trans, tf, dlen in self.docs:
            common = q_terms.intersection(tf)
            if not common:
                continue
            # Cobertura ponderada por IDF: quanto da consulta aparece neste exemplo (0..1)
            coverage = sum(self.idf[t] for t in common) / q_weight
            if coverage < min_score:
                continue
            norm_len = self.k1 * (1 - self.b + self.b * dlen / (self.avg_len or 1.0))
            bm25 = sum(self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm_len) for t in common)
            scored.append((coverage, bm25, orig, trans))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [(o, t, round(c, 3)) for c, _, o, t in scored[:top_k]]


# ---------------------------------------------------------------------------
# Cache do índice (refeito automaticamente quando o arquivo de memória muda)
# ---------------------------------------------------------------------------
_CACHE = {"path": None, "mtime": None, "index": None}


def load_memory_pairs(path=DEFAULT_MEMORY_PATH):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.items()) if isinstance(data, dict) else []
    except Exception:
        return []


def get_index(path=DEFAULT_MEMORY_PATH):
    """Devolve o índice da memória, reconstruindo-o só se o arquivo mudou."""
    try:
        mtime = os.path.getmtime(path) if os.path.exists(path) else None
    except OSError:
        mtime = None
    if _CACHE["index"] is None or _CACHE["path"] != path or _CACHE["mtime"] != mtime:
        _CACHE.update(path=path, mtime=mtime, index=TranslationMemoryIndex(load_memory_pairs(path)))
    return _CACHE["index"]


def is_enabled():
    """Liga/desliga pelo config.json ("rag_memory") ou pela variável MANGA_RAG (0/1)."""
    env = os.environ.get("MANGA_RAG", "").strip().lower()
    if env in ("0", "false", "off", "nao", "não"):
        return False
    if env in ("1", "true", "on", "sim"):
        return True
    enabled = True
    for cfg_path in _CONFIG_PATHS:
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    val = json.load(f).get("rag_memory")
                if val is not None:
                    enabled = bool(val)
        except Exception:
            continue
    return enabled


def retrieve_examples(texts, path=DEFAULT_MEMORY_PATH, top_k=DEFAULT_TOP_K_PER_TEXT,
                      max_examples=DEFAULT_MAX_EXAMPLES, min_score=DEFAULT_MIN_SCORE):
    """Busca exemplos para vários balões de uma vez, sem repetir e respeitando o limite total."""
    index = get_index(path)
    if not len(index):
        return []
    best = {}
    for text in texts or []:
        for orig, trans, cov in index.search(text, top_k=top_k, min_score=min_score):
            if len(orig) > MAX_EXAMPLE_LEN or len(trans) > MAX_EXAMPLE_LEN:
                continue
            # Variações só de pontuação ("大哥哥" / "大哥哥：" / "大哥哥～♡") contam como uma só
            key = normalize_text(orig)
            if key not in best or cov > best[key][2]:
                best[key] = (orig, trans, cov)
    ranked = sorted(best.values(), key=lambda v: v[2], reverse=True)
    return [(o, t) for o, t, _ in ranked[:max_examples]]


def build_rag_prompt_block(texts, path=DEFAULT_MEMORY_PATH, max_chars=DEFAULT_MAX_CHARS, **kwargs):
    """
    Monta o bloco de texto para anexar ao prompt de sistema.
    Retorna "" se desligado, sem memória, sem exemplos ou em caso de erro.
    """
    try:
        if not is_enabled():
            return ""
        examples = retrieve_examples(texts, path=path, **kwargs)
        if not examples:
            return ""
        header = ("\nMEMÓRIA DE TRADUÇÕES APROVADAS (frases parecidas já traduzidas; "
                  "use como referência de termos e tom, NÃO copie se o sentido for outro):\n")
        lines, total = [], len(header)
        for orig, trans in examples:
            line = f"- {json.dumps(orig, ensure_ascii=False)} -> {json.dumps(trans, ensure_ascii=False)}\n"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return header + "".join(lines) if lines else ""
    except Exception:
        return ""


if __name__ == "__main__":
    # Teste manual rápido:  python rag_memory.py "早安！" "有酒精"
    import sys
    queries = sys.argv[1:] or ["早安！", "謝謝你"]
    idx = get_index()
    print(f"[RAG] {len(idx)} frases indexadas | ativo: {is_enabled()}")
    for q in queries:
        print(f"\nConsulta: {q}")
        for o, t, c in idx.search(q, top_k=5):
            print(f"  {c:.2f}  {o}  ->  {t}")
    print("\nBloco para o prompt:" + (build_rag_prompt_block(queries) or " (vazio)"))
