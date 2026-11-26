"""
chapter_translator.py - O Gemini traduz o capítulo INTEIRO antes do laço página a página.

Como o plano grátis do Gemini aceita pedidos grandes, mandamos todas as falas do capítulo (em lotes de até
BATCH_SIZE balões, com o número da página em cada uma e as últimas falas do lote anterior como contexto).
A IA lê a história toda, então tom, gênero, apelidos e piadas ficam coerentes, e o capítulo gasta 1 a 3
pedidos em vez de dezenas. O resultado vai para o cache: o laço normal só traduz o que sobrar
(lotes que o Gemini recusar por conteúdo +18, falas inválidas). config.json: "gemini_chapter" (padrão ligado).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json

import chapter_context
import gemini_text

BATCH_SIZE = 120
CHAPTER_NOTE = (
    "\nMODO CAPÍTULO: os balões abaixo são de VÁRIAS páginas seguidas (campo 'pag'), na ordem de leitura. "
    "Leia tudo antes de traduzir e use a história inteira como contexto: quem fala com quem, gênero, "
    "apelidos e piadas que continuam entre páginas. Cada balão continua respeitando o seu 'max_chars'."
)


def enabled(cfg):
    return (cfg or {}).get("gemini_chapter", True) is not False and bool(gemini_text.key_pool(cfg))


def collect_items(pages_data, cache, at, src_lang="auto"):
    """[(página, balão do dossiê)] de tudo que ainda falta traduzir no capítulo."""
    items = []
    for p in pages_data:
        if at.is_credits_page(p["bubbles"]):
            continue
        todo = []
        for b in p["bubbles"]:
            orig = b["combined_text"].strip()
            if not orig or at.is_scan_watermark(orig):
                continue
            if orig in cache and at.is_valid_translation(orig, cache[orig]):
                continue
            todo.append((orig, b))
        if not todo:
            continue
        dossier, _ = at.build_page_spatial_dossier(todo, page_w=p.get("width", 1200), page_h=p.get("height", 1800),
                                                   src_lang=src_lang)
        for bal in dossier["baloes"]:
            text = bal["texto_original"]
            if at.is_scan_watermark(text) or at.translate_sfx_phrase(text):
                continue
            items.append((p.get("page", 1), bal))
    return items


def _batches(items, size=BATCH_SIZE):
    """Lotes de até `size` balões sem cortar uma página no meio (a não ser que a página sozinha passe do limite)."""
    batch, cur_page = [], None
    for page, bal in items:
        if len(batch) >= size and page != cur_page:
            yield batch
            batch = []
        batch.append((page, bal))
        cur_page = page
        if len(batch) >= size * 2:
            yield batch
            batch = []
    if batch:
        yield batch


def build_messages(batch, sys_prompt, context_block, at, src_lang="auto"):
    payload, dmap, ordered = at.prepare_chunk_payload([bal for _, bal in batch], src_lang=src_lang)
    for entry, (page, _) in zip(payload, batch):
        entry["pag"] = page
    body = {"ordem": "RTL", "modo": "capitulo", "total_baloes_lote": len(payload), "baloes": payload}
    messages = [
        {"role": "system", "content": sys_prompt + CHAPTER_NOTE + context_block},
        {"role": "user", "content": json.dumps(body, ensure_ascii=False, separators=(",", ":"))},
    ]
    return messages, dmap, ordered


def translate_chapter(pages_data, cache, cfg, engine_opts, at, is_adult=True, glossary=None, src_lang="auto",
                      ficha=None, ficha_module=None, progress=None):
    """Preenche `cache` com as traduções do capítulo. Devolve quantas falas foram traduzidas."""
    if not enabled(cfg):
        return 0
    items = collect_items(pages_data, cache, at, src_lang)
    if not items:
        return 0
    sys_prompt = at.build_dual_engine_system_prompt(is_adult=is_adult, glossary=glossary, src_lang=src_lang)
    if ficha and ficha_module is not None:
        try:
            sys_prompt += ficha_module.build_prompt_block(ficha, [bal["texto_original"] for _, bal in items])
        except Exception:
            pass
    batches = list(_batches(items))
    print(f"[*] [Capítulo] Gemini vai traduzir {len(items)} falas do capítulo inteiro em {len(batches)} pedido(s).")
    done, prev_pairs = 0, []
    for i, batch in enumerate(batches, 1):
        if progress:
            progress(f"Gemini lendo o capítulo inteiro ({i} de {len(batches)})")
        ctx = chapter_context.build_block({"_page_history": []}, cfg, same_page_pairs=prev_pairs) if prev_pairs else ""
        messages, dmap, ordered = build_messages(batch, sys_prompt, ctx, at, src_lang)
        try:
            resp = gemini_text.chat(messages, cfg, engine_opts, max_tokens=min(60000, 400 + len(batch) * 120))
        except gemini_text.GeminiBlocked as e:
            pages = sorted({p for p, _ in batch})
            print(f"[*] [Capítulo] Gemini recusou as páginas {pages[0]}-{pages[-1]} ({e}); elas seguem pelo caminho normal.")
            continue
        except gemini_text.GeminiQuotaExhausted as e:
            print(f"[*] [Capítulo] {e}. O resto segue página por página.")
            break
        except Exception as e:
            print(f"[!] [Capítulo] Falha no Gemini ({e}). O resto segue página por página.")
            break
        parsed = at.extract_json_from_response(at._strip_think_tags(resp))
        if not parsed:
            continue
        try:
            mapped = at.map_ai_response_to_bubbles(parsed, ordered, dmap)
        except Exception:
            continue
        page_of = {bal["orig_raw"]: p for p, bal in batch}
        for orig, trans in mapped.items():
            cleaned = at.clean_ai_translation(trans, original_text=orig, is_adult=is_adult, src_lang=src_lang)
            if cleaned and cleaned.strip().lower() != orig.strip().lower() and at.is_valid_translation(orig, cleaned):
                cache[orig] = cleaned
                done += 1
                prev_pairs.append((orig, cleaned))
                chapter_context.remember_page(engine_opts, page_of.get(orig, 0), [(orig, cleaned)])
    if done:
        engine_opts["_chapter_gemini_used"] = True
    print(f"[+] [Capítulo] {done} de {len(items)} falas traduzidas com o capítulo inteiro como contexto.")
    return done
