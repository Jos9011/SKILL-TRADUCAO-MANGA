# -*- coding: utf-8 -*-
"""
typography_ptbr.py - Motor de Tipografia Calibrada para Mangás em Português (PT-BR)
Garante métrica correta para acentos em CAIXA ALTA (ÁÇÃÊÓÚ), entrelinha limpa,
escala consistente na página e evita hifenizações feias em palavras curtas.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import numpy as np
from PIL import ImageFont

try:
    import pyphen
    _HYPHEN_DIC = pyphen.Pyphen(lang="pt_BR")
except Exception:
    _HYPHEN_DIC = None


def select_clean_font(text, fonts_map, is_shout=False, is_thought=False):
    """
    Seleciona fonte consistente para o balão:
    - Evita trocar para fonte de grito em saudações normais com um único '!'.
    - Mantém a mesma identidade visual nos diálogos da página.
    """
    clean = (text or "").strip()
    is_real_shout = bool(
        is_shout
        or clean.endswith("!!")
        or clean.endswith("!?")
        or clean.endswith("?!")
        or clean.endswith("!?!")
    )
    if is_real_shout:
        for k in ("shout", "komika", "anime_ace", "dialogue"):
            p = fonts_map.get(k)
            if p and os.path.exists(p):
                return p

    if is_thought or (clean.startswith("(") and clean.endswith(")")):
        for k in ("dialogue_italic", "anime_ace", "dialogue"):
            p = fonts_map.get(k)
            if p and os.path.exists(p):
                return p

    for k in ("anime_ace", "komika", "dialogue"):
        p = fonts_map.get(k)
        if p and os.path.exists(p):
            return p
    return fonts_map.get("fallback", "arial.ttf")


def measure_ptbr_line_height(draw, font, line_spacing=1.22):
    """Mede altura real de linha considerando acentos maiúsculos do PT-BR (ÁÇÃÊÓÚ)."""
    bb = draw.textbbox((0, 0), "ÁÇÃÊÓÚg", font=font)
    raw_h = max(8.0, float(bb[3] - bb[1]))
    return raw_h * line_spacing


def _hyphenate_long_word(draw, word, font, max_w, measure_fn, stroke_width=0, min_len=8):
    """Hifeniza somente palavras longas (>= 8 letras) quando realmente não cabem."""
    if not _HYPHEN_DIC or len(word) < min_len:
        return None
    parts = _HYPHEN_DIC.inserted(word).split("-")
    if len(parts) <= 1:
        return None
    left = ""
    best = None
    for idx in range(len(parts) - 1):
        cand_left = left + parts[idx]
        if len(cand_left) < 3:
            left = cand_left
            continue
        test_left = cand_left + "-"
        if measure_fn(draw, test_left, font, stroke_width) <= max_w:
            best = (test_left, "".join(parts[idx + 1:]))
            left = cand_left
        else:
            break
    return best


def wrap_balanced_ptbr(draw, text, font, max_w, measure_fn, stroke_width=0,
                       band_profile=None, allow_hyphen=False, max_k=8):
    """Linhas equilibradas (formato diamante/oval) respeitando o perfil de largura real do balão."""
    words = text.split()
    if not words:
        return []

    def _allowed_w(line_idx, total_lines):
        if not band_profile or total_lines <= 1:
            return max_w
        frac = (line_idx + 0.5) / float(total_lines)
        ys = [p[0] for p in band_profile]
        ws = [p[1] for p in band_profile]
        return min(max_w, float(np.interp(frac, ys, ws)))

    best_lines = None
    best_score = float("inf")

    # Até 8 linhas como sempre; com max_k > 8 (quadros estreitos e altos), só se nada couber tenta mais linhas
    k_values = list(range(1, min(len(words), 8) + 1))
    k_values += list(range(9, min(len(words) + 6, max_k) + 1))
    for target_k in k_values:
        if target_k > 8 and best_lines is not None:
            break
        work_words = list(words)
        lines = []
        idx = 0
        ok = True
        total_chars = sum(len(w) for w in work_words) + max(0, len(work_words) - 1)
        avg_chars = total_chars / float(target_k)

        for li in range(target_k):
            if idx >= len(work_words):
                break
            lim_w = _allowed_w(li, target_k)
            curr = work_words[idx]
            idx += 1

            if measure_fn(draw, curr, font, stroke_width) > lim_w:
                if allow_hyphen:
                    hyph = _hyphenate_long_word(draw, curr, font, lim_w, measure_fn, stroke_width)
                    if hyph:
                        lines.append(hyph[0])
                        work_words = work_words[:idx] + [hyph[1]] + work_words[idx:]
                        continue
                ok = False
                break

            while idx < len(work_words):
                rem_lines = target_k - li - 1
                rem_words = len(work_words) - idx
                if rem_lines > 0 and rem_words <= rem_lines:
                    break
                cand = curr + " " + work_words[idx]
                if measure_fn(draw, cand, font, stroke_width) <= lim_w:
                    if rem_lines > 0 and len(curr) >= avg_chars * 0.85 and len(cand) > avg_chars * 1.22:
                        break
                    curr = cand
                    idx += 1
                else:
                    break
            lines.append(curr)

        if not ok or idx < len(work_words):
            continue

        widths = [measure_fn(draw, ln, font, stroke_width) for ln in lines]
        penalty = 0.0
        if len(lines) > 1:
            last_w_tokens = lines[-1].split()
            if len(last_w_tokens) == 1 and len(last_w_tokens[0]) <= 3:
                penalty += 45.0
            mean_w = float(np.mean(widths))
            penalty += float(np.std(widths)) / max(1.0, mean_w) * 30.0
        penalty += sum(20.0 for ln in lines if ln.endswith("-"))

        if penalty < best_score:
            best_score = penalty
            best_lines = lines

    return best_lines


def fit_text_ptbr(draw, text, max_w, max_h, font_path, measure_fn,
                  stroke_width=1, band_profile=None, page_w=1280, is_display=False, min_line_w=None):
    """(font, lines, line_h) com escala consistente, respiro para acentos PT-BR e sem hífen desnecessário."""
    clean = (text or "").strip()
    if not clean:
        f = ImageFont.truetype(font_path, 16)
        return f, [], measure_ptbr_line_height(draw, f, 1.22)

    usable_w = max(30.0, float(max_w) * 0.94)
    usable_h = max(24.0, float(max_h) * 0.92)
    scaled_prof = None
    if band_profile:
        scaled_prof = [(py, max(26.0, pw * 0.94)) for py, pw in band_profile]

    base_fs = max(18, min(30, int(round(page_w * 0.0205))))
    max_fs = min(46, int(round(base_fs * 1.45))) if is_display else min(base_fs + 3, int(usable_h * 0.42))
    max_fs = max(16, max_fs)
    min_fs = max(14, int(round(page_w * 0.0115)))
    # Quadro de narração estreito e alto: aceita mais de 8 linhas (o original em inglês costuma ter 10+)
    max_k = 30 if usable_h >= 1.8 * usable_w else 8

    def _search(hi_fs, lo_fs, lead, allow_hyphen=False):
        for fs in range(hi_fs, lo_fs - 1, -1):
            font = ImageFont.truetype(font_path, fs)
            line_h = measure_ptbr_line_height(draw, font, lead)
            max_lines = int(usable_h // line_h)
            if max_lines < 1:
                continue
            lines = wrap_balanced_ptbr(
                draw, clean, font, usable_w, measure_fn,
                stroke_width=stroke_width,
                band_profile=scaled_prof,
                allow_hyphen=allow_hyphen,
                max_k=max_k,
            )
            if lines and len(lines) <= max_lines:
                total_h = len(lines) * line_h
                if total_h <= usable_h + 2.0:
                    return font, lines, line_h
        return None

    # 1. Ideal: entrelinha folgada (1.22) sem hifenização
    res = _search(max_fs, min_fs, 1.22, allow_hyphen=False)
    if res:
        return res

    # 2. Compacta suave (1.15) ainda sem hifenização e legível
    res = _search(min(max_fs, min_fs + 5), max(12, min_fs - 2), 1.15, allow_hyphen=False)
    if res:
        return res

    # 3. Permite hifenizar palavras longas (>= 8 letras)
    res = _search(min(max_fs, min_fs + 3), 11, 1.14, allow_hyphen=True)
    if res:
        return res

    # 4. Último recurso: nunca passa da largura do balão (antes saía uma linha só atravessando a página)
    safe_w = usable_w
    if scaled_prof:  # balão que afina (oval, degrau): usa a largura segura, não a maior
        safe_w = min(usable_w, max(26.0, float(np.percentile([pw for _, pw in scaled_prof], 25))))
    if min_line_w:  # a largura que o texto original ocupava cabe no quadro (o perfil pode juntar quadros vizinhos)
        safe_w = max(safe_w, min(usable_w, float(min_line_w)))
    # Ordem: palavras inteiras (fonte 11 -> 9) > hífen por sílaba > corte por letras (último caso)
    font, line_h, lines = None, 0.0, []
    for mode in ("none", "syllable", "chars"):
        for fs in range(11, 8, -1):
            font = ImageFont.truetype(font_path, fs)
            line_h = measure_ptbr_line_height(draw, font, 1.10)
            lines = wrap_hard_ptbr(draw, clean, font, safe_w, measure_fn, stroke_width, split_mode=mode)
            fits_w = all(measure_fn(draw, ln, font, stroke_width) <= safe_w + 0.5 for ln in lines)
            if lines and fits_w and len(lines) * line_h <= usable_h + 2.0:
                return font, lines, line_h
    return font, lines or [clean], line_h


def _syllable_split(draw, word, font, max_w, measure_fn, stroke_width=0):
    """Maior prefixo de sílabas (>= 2 letras, sobrando >= 2) que cabe com hífen: 'MU-' + 'DARAM.'"""
    if not _HYPHEN_DIC:
        return None
    parts = _HYPHEN_DIC.inserted(word).split("-")
    best = None
    for idx in range(1, len(parts)):
        left, right = "".join(parts[:idx]), "".join(parts[idx:])
        if sum(c.isalpha() for c in left) < 2 or sum(c.isalpha() for c in right) < 2:
            continue
        if measure_fn(draw, left + "-", font, stroke_width) <= max_w:
            best = (left + "-", right)
        else:
            break
    return best


def _split_word_to_width(draw, word, font, max_w, measure_fn, stroke_width=0, split_mode="chars"):
    """Divide uma palavra larga demais: por sílaba (PT-BR) e, se permitido, por letras (>= 3 de cada lado)."""
    if split_mode == "none":
        return [word]
    pieces, rest = [], word
    while rest and measure_fn(draw, rest, font, stroke_width) > max_w:
        syl = _syllable_split(draw, rest, font, max_w, measure_fn, stroke_width)
        if syl:
            pieces.append(syl[0])
            rest = syl[1]
            continue
        if split_mode != "chars":
            break
        cut = len(rest) - 3
        while cut >= 3 and measure_fn(draw, rest[:cut] + "-", font, stroke_width) > max_w:
            cut -= 1
        if cut < 3:
            break
        pieces.append(rest[:cut] + "-")
        rest = rest[cut:]
    if rest:
        pieces.append(rest)
    return pieces


def wrap_hard_ptbr(draw, text, font, max_w, measure_fn, stroke_width=0, split_mode="chars"):
    """Quebra gulosa por palavras que respeita max_w. split_mode: 'none', 'syllable' ou 'chars'."""
    lines, curr = [], ""
    for word in (text or "").split():
        for piece in _split_word_to_width(draw, word, font, max_w, measure_fn, stroke_width, split_mode):
            cand = f"{curr} {piece}" if curr else piece
            if curr and (curr.endswith("-") or measure_fn(draw, cand, font, stroke_width) > max_w):
                lines.append(curr)
                curr = piece
            else:
                curr = cand
    if curr:
        lines.append(curr)
    return lines
