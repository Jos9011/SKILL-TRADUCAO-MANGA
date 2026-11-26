"""
chapter_context.py - Contexto entre páginas para a IA não traduzir cada página "no escuro".

Até a v0.8.0 cada pedido levava só uma página (em lotes de até 10 balões) e a IA não sabia o que tinha
acontecido antes. Aqui guardamos as últimas falas já traduzidas (original -> tradução) e montamos um
bloco curto para o prompt: a IA mantém tom, gênero, apelidos e piadas que continuam de uma página para outra.
config.json: "context_pages" (0 a 3, padrão 2).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

MAX_LINES_PER_PAGE = 8
MAX_CHARS = 1400  # ~400 tokens: cabe no limite de 8 mil tokens por minuto do Groq junto com o lote


def pages_from(cfg):
    try:
        return max(0, min(3, int((cfg or {}).get("context_pages", 2))))
    except (TypeError, ValueError):
        return 2


def remember_page(engine_opts, page_num, pairs):
    """Guarda as falas traduzidas de uma página: pairs = [(original, tradução), ...] na ordem de leitura."""
    hist = engine_opts.setdefault("_page_history", [])
    clean = [(o.strip(), t.strip()) for o, t in pairs if o and t and o.strip() and t.strip()]
    if not clean:
        return
    if hist and hist[-1]["page"] == page_num:
        hist[-1]["pairs"].extend(clean)
    else:
        hist.append({"page": page_num, "pairs": clean})
    del hist[:-3]  # no máximo 3 páginas guardadas


def _short(text, limit=140):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_block(engine_opts, cfg=None, current_page=None, same_page_pairs=None):
    """Bloco de prompt com as falas anteriores (páginas anteriores + lotes já feitos desta página)."""
    n_pages = pages_from(cfg)
    lines = []
    if n_pages:
        hist = [h for h in engine_opts.get("_page_history", []) if h["page"] != current_page][-n_pages:]
        for h in hist:
            for o, t in h["pairs"][-MAX_LINES_PER_PAGE:]:
                lines.append(f"(pág {h['page']}) {_short(o)} => {_short(t)}")
    for o, t in (same_page_pairs or [])[-MAX_LINES_PER_PAGE:]:
        lines.append(f"(esta página) {_short(o)} => {_short(t)}")
    if not lines:
        return ""
    while lines and sum(len(l) + 1 for l in lines) > MAX_CHARS:
        lines.pop(0)  # descarta as mais antigas primeiro
    return ("\n\nCONTEXTO DA CENA (falas anteriores já traduzidas, só para referência; NÃO traduza de novo e "
            "NÃO inclua na resposta). Mantenha o mesmo tom, os mesmos nomes e o gênero de quem fala:\n- "
            + "\n- ".join(lines))
