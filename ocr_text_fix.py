"""
ocr_text_fix.py - Correções do texto lido pelo OCR e checagem de inglês residual na tradução

1. order_horizontal_lines: ordena as linhas de um balão de cima para baixo. Duas linhas só
   são da mesma "fileira" se se sobrepõem de verdade na vertical (antes era uma grade fixa
   de 22 px, que trocava a ordem em quadros de narração com linhas próximas:
   "SO MUCH HAS CHANGED" virava "MUCH SO HAS CHANGED").
2. normalize_case_lines: em balões escritos em CAIXA ALTA, corrige letras minúsculas soltas
   do OCR ("OTAKu" -> "OTAKU", "YOu?!" -> "YOU?!", "THhat" -> "THAT").
3. is_noise_text: identifica lixo do OCR (ex: "h3", leitura errada de um efeito sonoro
   desenhado), que não deve ser traduzido nem apagado da página.
4. english_residue: palavras inglesas comuns que a IA copiou do original para a tradução
   ("YOU'RE SO inteligente", "tinha sido UNDER"). Nomes próprios não contam.
5. looks_like_romaji: nomes japoneses romanizados ("TOKITO", "MANABU") que o separador de
   palavras coladas (wordninja) não deve quebrar ("TOKITO" virava "TOKI TO").
6. fix_ocr_confusions: em CAIXA ALTA, o RapidOCR lê U como L ("QLITE", "YOLR", "PENT-LP");
   também "...?" lido como "2?" e parênteses/colchetes soltos ("(SO", "[WHAT!").

Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import re

_CJK_RE = re.compile(r'[぀-ヿ㐀-䶿一-鿿가-힯ᄀ-ᇿ㄰-㆏]')
_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:'[A-Za-z]+)?")

# ---------------------------------------------------------------------------
# 1. Ordem das linhas
# ---------------------------------------------------------------------------
def order_horizontal_lines(blocks, min_overlap=0.5):
    """
    Ordena blocos de linha (dicts com "box" = [x0, y0, x1, y1]) em ordem de leitura ocidental.
    Uma linha entra na fileira anterior só se a sobreposição vertical for >= min_overlap da
    menor altura; dentro da fileira, da esquerda para a direita.
    """
    items = sorted(blocks, key=lambda b: (float(b["box"][1]) + float(b["box"][3])) / 2.0)
    rows = []
    for b in items:
        y0, y1 = float(b["box"][1]), float(b["box"][3])
        h = max(1.0, y1 - y0)
        if rows:
            row = rows[-1]
            overlap = min(y1, row["y1"]) - max(y0, row["y0"])
            if overlap >= min_overlap * min(h, row["h"]):
                row["items"].append(b)
                row["y0"], row["y1"] = min(row["y0"], y0), max(row["y1"], y1)
                row["h"] = min(row["h"], h)
                continue
        rows.append({"y0": y0, "y1": y1, "h": h, "items": [b]})
    return [b for row in rows for b in sorted(row["items"], key=lambda it: float(it["box"][0]))]


# ---------------------------------------------------------------------------
# 2. Caixa alta
# ---------------------------------------------------------------------------
def _fix_doubled_letter(word):
    """'THhat' -> 'THAT': o OCR às vezes lê uma letra maiúscula duas vezes, a 2ª minúscula."""
    out, i = [], 0
    while i < len(word):
        c = word[i]
        out.append(c)
        if c.isupper() and i + 1 < len(word) and word[i + 1] == c.lower() and word[i + 1] != c:
            i += 2
            continue
        i += 1
    return "".join(out)


def normalize_case_lines(lines, min_letters=4, min_upper_ratio=0.6):
    """Se o balão está em CAIXA ALTA, sobe as minúsculas soltas que o OCR deixou."""
    lines = [str(l or "") for l in (lines or [])]
    joined = " ".join(lines)
    if not joined.strip() or _CJK_RE.search(joined):
        return lines
    cased = [c for c in joined if c.isupper() or c.islower()]
    if len(cased) < min_letters:
        return lines
    uppers = sum(1 for c in cased if c.isupper())
    if uppers / len(cased) < min_upper_ratio or uppers == len(cased):
        return lines
    return [_WORD_RE.sub(lambda m: _fix_doubled_letter(m.group(0)).upper(), l) for l in lines]


# ---------------------------------------------------------------------------
# 3. Lixo do OCR
# ---------------------------------------------------------------------------
def is_noise_text(text):
    """
    True para blocos curtíssimos que misturam letra e número sem formar palavra
    (ex: "h3", "4a", "l1"). Esses blocos costumam ser efeitos sonoros desenhados lidos
    errado; traduzir e apagar estraga o desenho.
    """
    s = str(text or "")
    if _CJK_RE.search(s):
        return False
    core = re.sub(r"[^0-9A-Za-zÀ-ÖØ-öø-ÿ]", "", s)
    if not 1 <= len(core) <= 4:
        return False
    return bool(re.search(r"\d", core)) and bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", core))


# ---------------------------------------------------------------------------
# 4. Inglês residual
# ---------------------------------------------------------------------------
# Palavras inglesas comuns em diálogo. Ficaram de fora as que também existem em português
# ("a", "as", "no", "me", "do", "se", "come", "for", "real", "total", "late", "grade", "to")
# e as que viraram gíria em PT-BR ("ok", "time", "look", "live", "short", "show", "sexy").
_EN_COMMON = set("""
you you're youre you've you'll you'd your yours yourself i'm im i've ive i'll i'd it's its it'll
that's thats what's whats who's where's there's here's let's lets he's she's we're we've they're
they've isn't aren't wasn't weren't don't dont doesn't didn't can't cant couldn't won't wouldn't
shouldn't haven't hasn't hadn't ain't gonna wanna gotta
the an and or but if then than so because though although just only also too very really
quite pretty much many more most some any all every each other another such
is are was were be been being am have has had having do does did done doing will would
shall should can could may might must
he she it we they him her them his hers our ours their theirs my mine this that these those
there here where when why how what who whom which whose whatever whoever
in on at by with from into onto about over under after before between through during
without within around against along across behind beyond near off out up down away back
again still yet already ever never always often sometimes now today tonight tomorrow
yesterday morning evening night afternoon later soon
yes yeah yep nope not nothing something anything everything someone anyone everyone nobody
please thanks thank sorry hello goodbye welcome well okay alright sure maybe
good bad better best worse worst great nice fine cool smart stupid dumb rough tough hard easy
big small little long short old new young first last next own same different whole
happy sad angry scared tired hungry glad afraid ready late early wrong right true false
love like want need know think feel see look come go get got make made take took give gave
say said tell told talk speak ask call keep let put seem try leave left feel felt find found
mean meant work play run walk stop start wait help hold turn change changed live die
grade school teacher student friend friends family house home room place world money time
day days year years way thing things people man's woman girl boy guy guys kid kids
""".split())
_EN_COLLISIONS = {"a", "as", "no", "me", "do", "se", "come", "for", "real", "total", "normal",
                  "to", "ok", "man", "fan", "show", "baby", "sexy", "bye", "oh", "ah", "uh", "hey",
                  "grade", "time", "look", "late", "short", "live", "play"}
_EN_COMMON -= _EN_COLLISIONS


def _words(text):
    s = str(text or "").replace("’", "'").replace("‘", "'")
    return [w.lower() for w in _WORD_RE.findall(s)]


def english_residue(orig_text, trans_text, protected=()):
    """
    Palavras inglesas comuns que aparecem no original E foram copiadas para a tradução.
    Original asiático nunca dispara (não há palavra copiada). `protected` = nomes a ignorar.
    """
    orig_words = set(_words(orig_text))
    if not orig_words:
        return []
    keep = {w.lower() for w in protected or ()}
    found = []
    for w in _words(trans_text):
        if w in _EN_COMMON and w in orig_words and w not in keep and w not in found:
            found.append(w)
    return found


# ---------------------------------------------------------------------------
# 5. Nomes japoneses romanizados
# ---------------------------------------------------------------------------
_ROMAJI_RE = re.compile(
    r"^(?:(?:kk|ss|tt|pp|cch)?(?:ky|gy|sh|ch|ny|hy|by|py|my|ry|ts|[kgsztdnhbpmyrwfj])?[aeiou]+|n(?![aeiouy]))+$",
    re.IGNORECASE,
)


def looks_like_romaji(word, min_len=5):
    """True para palavras formadas só por sílabas japonesas (ma-na-bu, to-ki-to, ki-ra-ra)."""
    w = str(word or "")
    return len(w) >= min_len and w.isalpha() and bool(_ROMAJI_RE.match(w))


# ---------------------------------------------------------------------------
# 6. Confusões típicas do OCR
# ---------------------------------------------------------------------------
_FALLBACK_VOCAB = _EN_COMMON | set("quite your true up couldn shouldn wouldn until used hurry cure "
                                   "turn suck cum out but just must sure us guy sound found".split())


def _word_cost(word):
    """Custo da palavra no dicionário do wordninja (menor = mais comum). 99 = desconhecida."""
    try:
        import wordninja
        return wordninja.DEFAULT_LANGUAGE_MODEL._wordcost.get(word, 99.0)
    except Exception:
        return 9.0 if word in _FALLBACK_VOCAB else 99.0


def _fix_l_as_u(word):
    """'QLITE' -> 'QUITE', 'YOLR' -> 'YOUR', 'LP' -> 'UP': troca L por U só se vira palavra bem mais comum."""
    if not word.isupper() or "L" not in word or len(word) < 2:
        return word
    low = word.lower()
    orig_cost = _word_cost(low)
    positions = [i for i, c in enumerate(word) if c == "L"][:3]
    best, best_cost = word, orig_cost
    for mask in range(1, 2 ** len(positions)):
        chars = list(low)
        for bit, pos in enumerate(positions):
            if mask >> bit & 1:
                chars[pos] = "u"
        cand = "".join(chars)
        cost = _word_cost(cand)
        if cost < best_cost:
            best, best_cost = cand.upper(), cost
    rare_to_common = orig_cost >= 13.5 and best_cost <= 12.5
    much_more_common = best_cost <= 9.0 and best_cost + 4.5 <= orig_cost
    return best if best != word and (rare_to_common or much_more_common) else word


def _fix_token(tok):
    base, sep, tail = tok.partition("'")  # "COLLDN'T": avalia só "COLLDN"
    return _fix_l_as_u(base) + sep + tail


def fix_ocr_confusions(lines):
    """Corrige U lido como L (só em CAIXA ALTA), '2?' final e parênteses/colchetes sem par."""
    lines = [str(l or "") for l in (lines or [])]
    joined = " ".join(lines)
    if not joined.strip() or _CJK_RE.search(joined):
        return lines
    out = [re.sub(r"[A-Z]+(?:'[A-Z]+)?", lambda m: _fix_token(m.group(0)), l) for l in lines]
    if len(out) >= 2 and re.fullmatch(r"\s*[2Z]\s*([?!]+)\s*", out[-1]):
        out[-1] = "..." + out[-1].strip()[1:]
    joined = " ".join(out)
    for open_c, close_c in (("(", ")"), ("[", "]")):
        if joined.count(open_c) and not joined.count(close_c):
            out = [l.replace(open_c, "") for l in out]
        elif joined.count(close_c) and not joined.count(open_c):
            out = [l.replace(close_c, "") for l in out]
    return [re.sub(r"\s{2,}", " ", l).strip() for l in out]
