"""
lider_capitulo.py - Agente Líder do capítulo (Fase 1 da arquitetura multiagente)

Roda UMA vez por capítulo, depois do OCR e antes da tradução: lê todas as falas do
capítulo junto com a Ficha da Obra atual e devolve só as NOVIDADES (personagem novo,
gênero, termo próprio da obra). As novidades entram na ficha (ficha_obra.py), que vai
no prompt de cada lote do Agente 2.

- Modelo: "lider_model" do config (padrão openai/gpt-oss-120b no Groq).
- Cota: o Groq limita cada chamada a ~8k tokens. As falas vão sem repetição e cortadas;
  se o capítulo for grande, o Líder lê em partes (no máximo MAX_PARTS chamadas).
- Anti-invenção: só fica na ficha o que aparece de fato no texto do capítulo.
- A chamada usa uma CÓPIA do estado do motor: nada que o Líder faça (cota, troca de
  modelo, fallback) muda o motor do tradutor. Resposta do Google de emergência é descartada.
- Qualquer erro aqui é engolido: o Líder nunca pode quebrar a tradução.

Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import copy
import json
import os
import re

import ficha_caminho
import ficha_obra

DEFAULT_LEADER_MODEL = "openai/gpt-oss-120b"
MAX_LINE_LEN = 120
MAX_CHARS_PER_PART = 3000
MAX_PARTS = 4
LEADER_MAX_TOKENS = 1500
MAX_NOVOS_PERSONAGENS = 15
MAX_NOVOS_TERMOS = 25

SYSTEM_PROMPT = (
    "Você é o LÍDER de tradução de uma obra (mangá/manhwa/manhua) para PT-BR.\n"
    "Você recebe a FICHA ATUAL da obra e as FALAS ORIGINAIS de um capítulo (texto de OCR, pode ter ruído).\n"
    "Devolva SOMENTE as NOVIDADES que ainda não estão na ficha:\n"
    "1. PERSONAGENS: só pessoas com NOME PRÓPRIO escrito nas falas. Use o nome COMPLETO como aparece "
    "(ex: 'MANABU TOKITO', não só 'MANABU'); em 'pt', escreva com maiúscula só nas iniciais "
    "('Manabu Tokito'); mantenha honoríficos (-kun/-san/-sama). Gênero M, F ou ?: deduza pelo contexto "
    "(um nome em quadro de narração junto de falas em 1ª pessoa costuma ser o narrador; pronomes he/she, "
    "his/her, 'woman', 'girl' etc.). Nota curta e CERTA (papel ou relação, ex: 'protagonista e narrador').\n"
    "2. APELIDOS (ex: 'Otaku', 'Ota') NÃO são personagens: registre na nota de quem RECEBE o apelido "
    "(ex: nota de Manabu: 'Kirara o chama de \"Otaku\"'). Cuidado com quem chama e quem é chamado.\n"
    "3. Personagens da ficha com gênero '?', se o capítulo deixar o gênero claro.\n"
    "4. TERMOS próprios da obra (técnicas, lugares, organizações, títulos) que se repetem, com tradução "
    "fixa. NÃO inclua palavras comuns de dicionário.\n"
    "NÃO chute: se não tiver certeza de algo, deixe de fora (nada de 'possível', 'talvez', 'provavelmente'). "
    "NÃO traduza as falas. Ignore onomatopeias, títulos da obra e créditos de scan.\n"
    'Responda APENAS JSON válido: {"personagens":[{"original":"","pt":"","genero":"M|F|?","nota":""}],'
    '"termos":[{"original":"","pt":"","nota":""}]}\n'
    'Sem novidades: {"personagens":[],"termos":[]}'
)
_SPECULATIVE_RE = re.compile(
    r"(?i)\b(poss[ií]vel|possivelmente|talvez|provavelmente|parece ser|pode ser|suposto|incerto|"
    r"maybe|possibly|probably|perhaps|unclear|unknown)\b"
)


def leader_enabled(config=None):
    return ficha_obra.is_enabled(config) and not (
        isinstance(config, dict) and config.get("lider_capitulo") is False
    )


def prepare_lines(texts, max_line_len=MAX_LINE_LEN):
    """Falas do capítulo sem repetição, sem espaços extras e cortadas no tamanho máximo."""
    seen, lines = set(), []
    for t in texts or []:
        s = re.sub(r"\s+", " ", str(t or "")).strip()
        key = ficha_obra.normalize_key(s)
        if len(key.replace(" ", "")) < 2 or key in seen:
            continue
        seen.add(key)
        lines.append(s if len(s) <= max_line_len else s[:max_line_len].rstrip() + "…")
    return lines


def split_parts(lines, max_chars=MAX_CHARS_PER_PART, max_parts=MAX_PARTS):
    """Divide as falas em partes que cabem numa chamada. Devolve (partes, falas_deixadas_de_fora)."""
    parts, cur, cur_len = [], [], 0
    for line in lines:
        if cur and cur_len + len(line) + 1 > max_chars:
            parts.append(cur)
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        parts.append(cur)
    dropped = sum(len(p) for p in parts[max_parts:])
    return parts[:max_parts], dropped


def summary_for_leader(ficha, max_chars=1200):
    """Resumo compacto da ficha atual para o Líder saber o que já existe."""
    parts = [f"{p['original']}={p.get('pt') or p['original']}({p.get('genero', '?')})"
             for p in ficha.get("personagens") or []]
    parts += [f"{t['original']}={t['pt']}" for t in ficha.get("termos") or []]
    out, total = [], 0
    for item in parts:
        if total + len(item) + 2 > max_chars:
            break
        out.append(item)
        total += len(item) + 2
    return "; ".join(out) if out else "(vazia)"


def build_messages(lines, ficha, obra="", capitulo="", src_lang="auto", part_label=""):
    user = (
        f"OBRA: {obra or ficha.get('obra') or '?'}\n"
        f"CAPÍTULO: {capitulo or '?'}{part_label}\n"
        f"IDIOMA ORIGINAL: {src_lang}\n"
        f"FICHA ATUAL: {summary_for_leader(ficha)}\n"
        "FALAS DO CAPÍTULO (em ordem de leitura):\n" + "\n".join(lines)
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_response(text):
    """Extrai o JSON {"personagens": [...], "termos": [...]} da resposta. None se não houver."""
    if not text:
        return None
    clean = re.sub(r"<think>.*?</think>", "", str(text), flags=re.DOTALL)
    clean = re.sub(r"```(?:json)?", "", clean).strip()
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(clean[start:end + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    pers = data.get("personagens")
    terms = data.get("termos")
    if not isinstance(pers, list) and not isinstance(terms, list):
        return None
    return {"personagens": pers if isinstance(pers, list) else [],
            "termos": terms if isinstance(terms, list) else []}


def _tidy_item(item, kind):
    """Descarta palpites ('possível...', '?') e acerta a caixa de nomes em CAIXA ALTA ('MANABU' -> 'Manabu')."""
    text = " ".join(str(item.get(k) or "") for k in ("original", "pt", "nota"))
    if _SPECULATIVE_RE.search(text) or "?" in str(item.get("original") or "") + str(item.get("pt") or ""):
        return None
    item = dict(item)
    pt = str(item.get("pt") or item.get("original") or "").strip()
    if kind == "personagens" and len(pt) > 2 and pt.isupper():
        item["pt"] = " ".join(w[:1] + w[1:].lower() for w in pt.split(" "))
    return item


def filter_grounded(novidades, lines):
    """Mantém só nomes/termos que aparecem de fato nas falas (anti-alucinação) e sem palpites."""
    norm_text = ficha_obra.normalize_key("\n".join(lines))
    out = {"personagens": [], "termos": []}
    for kind, limit in (("personagens", MAX_NOVOS_PERSONAGENS), ("termos", MAX_NOVOS_TERMOS)):
        for item in (novidades or {}).get(kind) or []:
            if not isinstance(item, dict):
                continue
            item = _tidy_item(item, kind)
            if item and ficha_obra.mentions(ficha_obra.normalize_key(item.get("original")), norm_text):
                out[kind].append(item)
            if len(out[kind]) >= limit:
                break
    return out


def run_leader(lines, ficha, call_fn, obra="", capitulo="", src_lang="auto", log=print):
    """
    Chama o Líder parte por parte e mescla as novidades na ficha (em memória).
    Devolve (relatório somado, número de partes que responderam).
    """
    total = {"personagens_novos": [], "termos_novos": [], "generos_completados": [], "conflitos": []}
    parts, dropped = split_parts(lines)
    if dropped:
        log(f"[*] [Líder] Capítulo longo: {dropped} fala(s) ficaram de fora para poupar cota.")
    ok_parts = 0
    for i, part in enumerate(parts, 1):
        label = f" (parte {i} de {len(parts)})" if len(parts) > 1 else ""
        try:
            resp = call_fn(build_messages(part, ficha, obra, capitulo, src_lang, label), LEADER_MAX_TOKENS)
        except Exception as e:
            log(f"[!] [Líder] Falha na chamada{label}: {e}")
            continue
        parsed = parse_response(resp)
        if parsed is None:
            log(f"[!] [Líder] Resposta sem JSON válido{label}; ignorada.")
            continue
        ok_parts += 1
        report = ficha_obra.merge_novidades(ficha, filter_grounded(parsed, part), capitulo=capitulo)
        for k in total:
            total[k].extend(report[k])
    return total, ok_parts


def _isolated_opts(engine_opts, leader_model):
    """Cópia do estado do motor: o Líder não pode esgotar/alternar nada do tradutor."""
    opts = {}
    for k, v in (engine_opts or {}).items():
        opts[k] = copy.copy(v) if isinstance(v, (set, dict, list)) else v
    if leader_model and opts.get("active_engine", "groq") == "groq":
        opts["preferred_model"] = leader_model
        opts["active_model_by_key"] = {}
    opts["_fallback_originals"] = set()
    opts["_google_announced"] = True  # não anuncia "motor de emergência" por causa do Líder
    return opts


def make_call_fn(engine_opts, execute_fn, leader_model=DEFAULT_LEADER_MODEL):
    """Adapta o roteador de IAs do auto_translate (execute_translation_request) para o Líder."""
    def call(messages, max_tokens):
        opts = _isolated_opts(engine_opts, leader_model)
        resp = execute_fn(messages, engine_opts=opts, is_adult=True, max_tokens=max_tokens,
                          is_batch=False, raise_on_oversize=False)
        if opts.get("_last_used_fallback"):
            return ""  # tradução do Google de emergência não serve como resposta do Líder
        return resp or ""
    return call


def _log_report(report, log):
    novos_p, novos_t = report["personagens_novos"], report["termos_novos"]
    if not (novos_p or novos_t or report["generos_completados"] or report["conflitos"]):
        log("[+] [Líder] Nenhuma novidade neste capítulo; ficha mantida.")
        return
    if novos_p:
        log(f"[+] [Líder] {len(novos_p)} personagem(ns) novo(s): {', '.join(novos_p[:8])}")
    if novos_t:
        log(f"[+] [Líder] {len(novos_t)} termo(s) novo(s): {', '.join(novos_t[:8])}")
    if report["generos_completados"]:
        log(f"[+] [Líder] Gênero definido para: {', '.join(report['generos_completados'][:8])}")
    if report["conflitos"]:
        log(f"[!] [Líder] {len(report['conflitos'])} divergência(s) com a ficha (veja 'conflitos' no JSON).")


def run_for_chapter(manga_dir, obra_nome, texts, engine_opts, execute_fn, config=None,
                    src_lang="auto", force=False, log=print):
    """
    Orquestra a Fase 1 para um capítulo. Devolve {"ficha", "path", "changed"} ou None se desligado.
    engine_opts=None significa sem IA disponível: usa a ficha existente sem chamar o Líder.
    """
    if not ficha_obra.is_enabled(config):
        return None
    d = os.path.abspath(str(manga_dir))
    path = ficha_obra.resolve_ficha_path(d)
    capitulo = os.path.basename(d)
    obra_nome = ficha_caminho.obra_display_name(d, path, fallback=obra_nome)
    ficha = ficha_obra.load_ficha(path, obra=obra_nome)
    ctx = {"ficha": ficha, "path": path, "changed": False}

    if engine_opts is None or not leader_enabled(config):
        return ctx
    if ficha_obra.chapter_already_read(ficha, capitulo) and not force:
        log(f"[*] [Líder] Capítulo '{capitulo}' já lido antes; usando a ficha salva.")
        return ctx
    lines = prepare_lines(texts)
    if not lines:
        return ctx

    model = (config or {}).get("lider_model") or DEFAULT_LEADER_MODEL
    log(f"[*] [Líder] Lendo o capítulo inteiro ({len(lines)} falas únicas) com '{model}'...")
    report, ok_parts = run_leader(lines, ficha, make_call_fn(engine_opts, execute_fn, model),
                                  obra=ficha.get("obra"), capitulo=capitulo, src_lang=src_lang, log=log)
    if ok_parts:
        ficha_obra.mark_chapter_read(ficha, capitulo)
        ctx["changed"] = True
        _log_report(report, log)
    else:
        log("[!] [Líder] Nenhuma resposta válida; tradução segue com a ficha atual.")
    return ctx


def save_if_changed(ctx):
    """Grava a ficha no fim da tradução, só se o Líder trouxe algo."""
    if ctx and ctx.get("changed") and ctx.get("path"):
        if ficha_obra.save_ficha(ctx["ficha"], ctx["path"]):
            print(f"[+] [Ficha] Ficha da obra salva em: {ctx['path']}")
            ctx["changed"] = False
            return True
    return False
