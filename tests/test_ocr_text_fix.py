"""
test_ocr_text_fix.py - Ordem das linhas, caixa alta, lixo do OCR e inglês residual.
As coordenadas vêm do OCR real de páginas de "Toshiue no Kuro Gal Doukyuusei" (scan em inglês).
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import unittest

import auto_translate
import ocr_text_fix as f


def _blocks(rows):
    """rows: (texto, x0, y0, largura, altura) -> blocos no formato do agrupador do OCR."""
    return [{"text": t, "box": [x, y, x + w, y + h]} for t, x, y, w, h in rows]


class TestLineOrder(unittest.TestCase):
    def _order(self, rows):
        return [b["text"] for b in f.order_horizontal_lines(_blocks(rows))]

    def test_centered_narration_lines_keep_reading_order(self):
        # Antes: grade fixa de 22 px colocava "MUCH" antes de "SO" (mesma faixa, x menor)
        self.assertEqual(self._order([("MUCH", 490, 1296, 60, 16), ("SO", 500, 1277, 30, 16),
                                      ("HAS", 494, 1312, 40, 16), ("CHANGED", 472, 1334, 90, 16)]),
                         ["SO", "MUCH", "HAS", "CHANGED"])
        self.assertEqual(self._order([("FAMILY'S", 776, 1406, 90, 17), ("MY", 803, 1386, 30, 17),
                                      ("CONGLO-", 773, 1426, 80, 17)]),
                         ["MY", "FAMILY'S", "CONGLO-"])
        self.assertEqual(self._order([("KNOWING", 662, 1675, 90, 17), ("THEY ARE", 662, 1713, 90, 17),
                                      ("WHERE", 672, 1694, 70, 17)]),
                         ["KNOWING", "WHERE", "THEY ARE"])
        self.assertEqual(self._order([("INCURABLE", 1129, 215, 100, 14), ("AN", 1165, 198, 25, 14),
                                      ("DISEASE.", 1134, 230, 90, 14)]),
                         ["AN", "INCURABLE", "DISEASE."])

    def test_words_on_the_same_line_go_left_to_right(self):
        self.assertEqual(self._order([("WORLD", 200, 100, 80, 20), ("HELLO", 100, 103, 80, 20),
                                      ("AGAIN", 100, 130, 80, 20)]),
                         ["HELLO", "WORLD", "AGAIN"])

    def test_grouping_uses_new_order(self):
        blocks = _blocks([("MUCH", 490, 1296, 60, 16), ("SO", 500, 1277, 30, 16),
                          ("HAS", 494, 1312, 40, 16), ("CHANGED", 472, 1334, 90, 16)])
        bubbles = auto_translate.smart_group_bubbles(blocks)
        self.assertEqual(len(bubbles), 1)
        self.assertEqual(bubbles[0]["lines"], ["SO", "MUCH", "HAS", "CHANGED"])


class TestCase(unittest.TestCase):
    def test_uppercase_bubbles_are_fixed(self):
        self.assertEqual(f.normalize_case_lines(["TEASING", "ME WITH", '"OTAKu."']),
                         ["TEASING", "ME WITH", '"OTAKU."'])
        self.assertEqual(f.normalize_case_lines(["YOu?!", "YOU", "WOULD'VE"]), ["YOU?!", "YOU", "WOULD'VE"])
        self.assertEqual(f.normalize_case_lines(["WELL,", "NEVER", "MIND ALL", "THhat."]),
                         ["WELL,", "NEVER", "MIND ALL", "THAT."])
        self.assertEqual(f.normalize_case_lines(["HoW", "ARE WE", "FEELING?"]), ["HOW", "ARE WE", "FEELING?"])

    def test_normal_text_is_untouched(self):
        for lines in (["You woke up from a very long sleep"], ["Who Are You?"], ["I am OK, Yu-kun"],
                      ["早安！"], ["OK"], ["ALL CAPS ALREADY"], []):
            self.assertEqual(f.normalize_case_lines(lines), lines)


class TestNoise(unittest.TestCase):
    def test_noise_blocks(self):
        for t in ("h3", "l1", "4a", "h 3"):
            self.assertTrue(f.is_noise_text(t), t)
        for t in ("P!", "YEP!", "WHAT!", "17", "!?", "...", "HERE! PUSA", "OK", "早", "I", ""):
            self.assertFalse(f.is_noise_text(t), t)


class TestEnglishResidue(unittest.TestCase):
    def test_copied_english_words_are_found(self):
        self.assertEqual(f.english_residue("YOU'RE! (SO SMART, OTAKU!", "YOU'RE SO inteligente, meu Ota!"),
                         ["you're", "so"])
        self.assertEqual(f.english_residue("MY FAMILY'S CONGLOMERATE HAD GONE UNDER",
                                           "O conglomerado da minha família tinha sido UNDER"), ["under"])
        self.assertEqual(f.english_residue("YOU'VE ENDED UP IN SOME PRETTY ROUGH CIRCUMSTANCES.",
                                           "Cê tá em umas ROUGH circunstâncias."), ["rough"])
        self.assertEqual(f.english_residue("MORNING, OTAKU.", "MORNING, OTAKU."), ["morning"])
        self.assertEqual(f.english_residue("Who are you?", "Quem é uh? You?"), ["you"])

    def test_names_portuguese_and_asian_text_are_fine(self):
        cases = [("KIRARA SAITO", "Kirara Saito"), ("Welcome home, Yu-kun!", "Bem-vindo de volta, Yu-kun!"),
                 ("MORNING, OTAKU.", "Bom dia, Otaku."), ("早安", "so good"),
                 ("I graduated from T University", "Eu me formei na Universidade T"),
                 ("Come here! No way!", "Vem cá! De jeito nenhum! Ele come tudo, no fim."),
                 ("Your tests ran late", "Seus exames atrasaram, o cachorro late"),
                 ("Hope is here", "Hope está aqui")]
        for orig, trans in cases:
            self.assertEqual(f.english_residue(orig, trans), [], (orig, trans))
        self.assertEqual(f.english_residue("Will you come?", "Will vem?", protected=["Will"]), [])

    def test_validator_rejects_mixed_translation(self):
        v = auto_translate.is_valid_translation
        self.assertFalse(v("YOU'RE! (SO SMART, OTAKU!", "YOU'RE SO inteligente, meu Ota!"))
        self.assertFalse(v("SO MUCH HAS CHANGED", "SO muito mudou"))
        self.assertTrue(v("SO MUCH HAS CHANGED", "Tanta coisa mudou"))
        self.assertTrue(v("YOU'RE SO SMART, OTAKU!", "Você é tão inteligente, Otaku!"))
        self.assertTrue(v("早安！", "Bom dia!"))

    def test_prompt_forbids_english_residue(self):
        self.assertIn("ZERO inglês residual", auto_translate.build_dual_engine_system_prompt(src_lang="en"))


class TestRomajiAndConfusions(unittest.TestCase):
    def test_romaji_names(self):
        for w in ("TOKITO", "MANABU", "KIRARA", "SHINJUKU", "NAKAMURA"):
            self.assertTrue(f.looks_like_romaji(w), w)
        for w in ("CONGLOMERATE", "HAPPENED", "WHENI", "OTA", "SMART"):
            self.assertFalse(f.looks_like_romaji(w), w)

    def test_l_read_instead_of_u(self):
        self.assertEqual(f.fix_ocr_confusions(["CHANGED", "QLITE", "A BIT."]), ["CHANGED", "QUITE", "A BIT."])
        self.assertEqual(f.fix_ocr_confusions(["YOLR TEN YEARS'", "PENT-LP"]), ["YOUR TEN YEARS'", "PENT-UP"])
        self.assertEqual(f.fix_ocr_confusions(["YOU COLLDN'T", "HELP IT!"]), ["YOU COULDN'T", "HELP IT!"])
        self.assertEqual(f.fix_ocr_confusions(["TRLE TO KIRARA'S WORD"]), ["TRUE TO KIRARA'S WORD"])
        same = ["CALL ME", "ALL", "LOT", "LULU", "HELLO", "LIKE", "ALONE", "FULL", "LEFT", "WILL", "You look nice"]
        self.assertEqual(f.fix_ocr_confusions(same), same)

    def test_punctuation_noise(self):
        self.assertEqual(f.fix_ocr_confusions(["WHO", "ARE", "YOU", "2?"]), ["WHO", "ARE", "YOU", "...?"])
        self.assertEqual(f.fix_ocr_confusions(["YOU'RE!", "(SO", "SMART, OTAKU!"]), ["YOU'RE!", "SO", "SMART, OTAKU!"])
        self.assertEqual(f.fix_ocr_confusions(["[WHAT!", "P!"]), ["WHAT!", "P!"])
        self.assertEqual(f.fix_ocr_confusions(["(WHISPER)", "HELLO"]), ["(WHISPER)", "HELLO"])
        self.assertEqual(f.fix_ocr_confusions(["17"]), ["17"])
        self.assertEqual(f.fix_ocr_confusions(["早安？"]), ["早安？"])

    @unittest.skipIf(auto_translate.wordninja is None, "wordninja não instalado")
    def test_word_splitter_keeps_japanese_names(self):
        r = auto_translate.repair_glued_text
        self.assertEqual(r("MANABU TOKITO"), "MANABU TOKITO")
        self.assertEqual(r("KIRARA SAITO"), "KIRARA SAITO")
        self.assertEqual(r("YOUWOKE UP"), "YOU WOKE UP")
        self.assertEqual(r("WHENI WAS 17"), "WHEN I WAS 17")


if __name__ == "__main__":
    unittest.main()
