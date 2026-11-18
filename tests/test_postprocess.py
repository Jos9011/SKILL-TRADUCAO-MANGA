# -*- coding: utf-8 -*-
"""
Testes de regressão do pós-processamento (clean_ai_translation / clean_ocr_scan_noise).

Cada caso aqui já quebrou uma tradução real. Ao criar uma regra nova em
auto_translate.py, rode:  python -m pytest tests -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_translate as at  # noqa: E402

clean = at.clean_ai_translation


# ---------------------------------------------------------------------------
# Fonte japonesa / coreana / chinesa: regras feitas para inglês NÃO podem disparar
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("trans, orig, src", [
    ("Você está bem?", "大丈夫？", "ja-JP"),
    ("Irmão mais velho, espera!", "お兄ちゃん、待って！", "ja-JP"),
    ("Por favor, não vá embora", "行かないで", "ja-JP"),
    ("Você está bem?", "괜찮아?", "ko-KR"),
    ("Não posso deixar você ir agora", "不能让你走", "zh-CN"),
])
def test_cjk_source_keeps_translation(trans, orig, src):
    assert clean(trans, original_text=orig, src_lang=src) == trans


def test_cjk_detected_even_without_src_lang():
    assert clean("Você está bem?", original_text="大丈夫？") == "Você está bem?"


# ---------------------------------------------------------------------------
# Gênero não pode ser forçado sem saber quem fala
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("trans", [
    "Quando eu era pequena, eu morava aqui",
    "Quando eu era pequeno, eu morava aqui",
    "Eu quero ser desejado",
    "Serei seu parceiro",
    "Não vou ficar nu",
])
def test_gender_is_not_forced(trans):
    assert clean(trans, original_text="When I was little, I lived here", src_lang="en-US") == trans


# ---------------------------------------------------------------------------
# Regras específicas de obras não podem destruir frases comuns
# ---------------------------------------------------------------------------
def test_yu_kun_rule_keeps_vamos():
    out = clean("Yu-kun, vamos embora!", original_text="Yu-kun, let's go!", src_lang="en-US")
    assert "vamos embora" in out.lower()


def test_hard_without_sexual_context_stays_dificil():
    out = clean("É difícil dizer isso", original_text="It is hard to say", src_lang="en-US")
    assert out == "É difícil dizer isso"


def test_hard_with_sexual_context_becomes_duro():
    out = clean("Seu pau está tão difícil", original_text="Your cock is so hard", src_lang="en-US")
    assert "duro" in out.lower()


def test_shop_does_not_trigger_jewelry_rewrite():
    out = clean("Vou te levar na loja", original_text="I'll take you to the shop", src_lang="en-US")
    assert out == "Vou te levar na loja"


def test_voce_kept_when_english_sentence_has_no_you():
    out = clean("Obrigado a você", original_text="Thanks a lot!", src_lang="en-US")
    assert "você" in out


# ---------------------------------------------------------------------------
# Comportamentos que DEVEM continuar funcionando
# ---------------------------------------------------------------------------
def test_moan_u_u_u_is_not_voce():
    assert "você" not in clean("Você... você... você...", original_text="u u u", src_lang="en-US").lower()


def test_short_latin_moan_is_truncated():
    assert clean("Ah, isso é muito bom demais", original_text="NGH!", src_lang="en-US") == "Ah,"


def test_ai_preamble_is_removed():
    assert clean("Aqui está a tradução: Olá, mundo!", original_text="Hello, world!", src_lang="en-US") == "Olá, mundo!"


def test_empty_result_is_not_invented():
    # Nunca inventar fala: se a limpeza esvaziar, devolve "" para outro motor tentar
    out = clean("Como uma IA, não posso ajudar.", original_text="Your cock is so big", src_lang="en-US")
    assert out == ""


# ---------------------------------------------------------------------------
# OCR: correções de espanhol só em obras em espanhol
# ---------------------------------------------------------------------------
def test_english_to_do_is_not_glued():
    assert at.clean_ocr_scan_noise("I have to do it today", src_lang="en-US") == "I have to do it today"


def test_spanish_fragment_is_fixed_in_spanish_work():
    assert at.clean_ocr_scan_noise("Muchas graci as por to do", src_lang="es-ES") == "Muchas gracias por todo"


def test_ocr_noise_skips_cjk():
    assert at.clean_ocr_scan_noise("待って to do", src_lang="ja-JP") == "待って to do"
