# -*- coding: utf-8 -*-
"""
Testes de regressão do pós-processamento (clean_ai_translation / clean_ocr_scan_noise).

Cada caso aqui já quebrou uma tradução real. Compatível com unittest e pytest.
Regra de ouro: Coeso e estritamente < 300 linhas.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_translate as at

clean = at.clean_ai_translation


class PostprocessRegressionTests(unittest.TestCase):
    # ---------------------------------------------------------------------------
    # Fonte japonesa / coreana / chinesa: regras feitas para inglês NÃO podem disparar
    # ---------------------------------------------------------------------------
    def test_cjk_source_keeps_translation(self):
        cases = [
            ("Você está bem?", "大丈夫？", "ja-JP"),
            ("Irmão mais velho, espera!", "お兄ちゃん、待って！", "ja-JP"),
            ("Por favor, não vá embora", "行かないで", "ja-JP"),
            ("Você está bem?", "괜찮아?", "ko-KR"),
            ("Não posso deixar você ir agora", "不能让你走", "zh-CN"),
        ]
        for trans, orig, src in cases:
            with self.subTest(trans=trans, orig=orig, src=src):
                self.assertEqual(clean(trans, original_text=orig, src_lang=src), trans)

    def test_cjk_detected_even_without_src_lang(self):
        self.assertEqual(clean("Você está bem?", original_text="大丈夫？"), "Você está bem?")

    # ---------------------------------------------------------------------------
    # Gênero não pode ser forçado sem saber quem fala
    # ---------------------------------------------------------------------------
    def test_gender_is_not_forced(self):
        cases = [
            "Quando eu era pequena, eu morava aqui",
            "Quando eu era pequeno, eu morava aqui",
            "Eu quero ser desejado",
            "Serei seu parceiro",
            "Não vou ficar nu",
        ]
        for trans in cases:
            with self.subTest(trans=trans):
                self.assertEqual(clean(trans, original_text="When I was little, I lived here", src_lang="en-US"), trans)

    # ---------------------------------------------------------------------------
    # Regras específicas de obras não podem destruir frases comuns
    # ---------------------------------------------------------------------------
    def test_yu_kun_rule_keeps_vamos(self):
        out = clean("Yu-kun, vamos embora!", original_text="Yu-kun, let's go!", src_lang="en-US")
        self.assertIn("vamos embora", out.lower())

    def test_hard_without_sexual_context_stays_dificil(self):
        out = clean("É difícil dizer isso", original_text="It is hard to say", src_lang="en-US")
        self.assertEqual(out, "É difícil dizer isso")

    def test_hard_with_sexual_context_becomes_duro(self):
        out = clean("Seu pau está tão difícil", original_text="Your cock is so hard", src_lang="en-US")
        self.assertIn("duro", out.lower())

    def test_shop_does_not_trigger_jewelry_rewrite(self):
        out = clean("Vou te levar na loja", original_text="I'll take you to the shop", src_lang="en-US")
        self.assertEqual(out, "Vou te levar na loja")

    def test_voce_kept_when_english_sentence_has_no_you(self):
        out = clean("Obrigado a você", original_text="Thanks a lot!", src_lang="en-US")
        self.assertIn("você", out)

    # ---------------------------------------------------------------------------
    # Comportamentos que DEVEM continuar funcionando
    # ---------------------------------------------------------------------------
    def test_moan_u_u_u_is_not_voce(self):
        self.assertNotIn("você", clean("Você... você... você...", original_text="u u u", src_lang="en-US").lower())

    def test_short_latin_moan_is_truncated(self):
        self.assertEqual(clean("Ah, isso é muito bom demais", original_text="NGH!", src_lang="en-US"), "Ah,")

    def test_ai_preamble_is_removed(self):
        self.assertEqual(clean("Aqui está a tradução: Olá, mundo!", original_text="Hello, world!", src_lang="en-US"), "Olá, mundo!")

    def test_empty_result_is_not_invented(self):
        # Nunca inventar fala: se a limpeza esvaziar, devolve "" para outro motor tentar
        out = clean("Como uma IA, não posso ajudar.", original_text="Your cock is so big", src_lang="en-US")
        self.assertEqual(out, "")

    # ---------------------------------------------------------------------------
    # OCR: correções de espanhol só em obras em espanhol
    # ---------------------------------------------------------------------------
    def test_english_to_do_is_not_glued(self):
        self.assertEqual(at.clean_ocr_scan_noise("I have to do it today", src_lang="en-US"), "I have to do it today")

    def test_spanish_fragment_is_fixed_in_spanish_work(self):
        self.assertEqual(at.clean_ocr_scan_noise("Muchas graci as por to do", src_lang="es-ES"), "Muchas gracias por todo")

    def test_ocr_noise_skips_cjk(self):
        self.assertEqual(at.clean_ocr_scan_noise("待って to do", src_lang="ja-JP"), "待って to do")


if __name__ == "__main__":
    unittest.main()
