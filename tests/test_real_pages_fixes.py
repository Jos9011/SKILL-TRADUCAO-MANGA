"""
test_real_pages_fixes.py - Correções medidas nas páginas originais 11-15 de um capítulo japonês (v0.8.8).

Cada caso veio da comparação original x traduzido: gotinhas de suor traduzidas ("っっ"), "HUG!!" apagado
com mancha, nuvem com duas frases misturadas, coluna "どーしても" que o detector não achou, retângulo branco
sobre a janela clara e largura derrubada por um resto de traço.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import unittest

import cv2
import numpy as np

import auto_translate
import balloon_assign as ba
import balloon_cavity as bc
import balloon_merge as bm
import ocr_recover
import ocr_text_fix as otf


def _page(bg=150):
    img = np.zeros((1800, 1300, 3), np.uint8)
    img[:] = bg
    return img


class TestNoiseAndLatin(unittest.TestCase):
    def test_sweat_marks_and_stray_letters_are_noise(self):
        for t in ("っっ", "つつ", "いc"):
            self.assertTrue(otf.is_noise_text(t), t)
        for t in ("はい", "声♥", "私も同じw", "!?", "ッ!!", "っ…", "っ"):
            self.assertFalse(otf.is_noise_text(t), t)

    def test_latin_sfx_stays_on_cjk_pages_only(self):
        self.assertTrue(otf.is_latin_display("HUG!", "ja-jp"))
        self.assertTrue(otf.is_latin_display("OK!", "ko"))
        self.assertFalse(otf.is_latin_display("HUG!", "en"))  # obra em inglês: traduz normalmente
        self.assertFalse(otf.is_latin_display("Hello there my friend", "ja"))
        self.assertFalse(otf.is_latin_display("声♥", "ja"))


class TestReadingOrder(unittest.TestCase):
    def test_two_sentences_in_one_cloud_do_not_mix(self):
        # pág 13: frase de cima (4 colunas) e frase de baixo (4 colunas), mesmas posições x
        top = [([239, 1277, 278, 1394], "いやー"), ([192, 1277, 237, 1640], "楓さんみたいな人が"),
               ([145, 1281, 178, 1506], "あんな激しい"), ([94, 1277, 133, 1508], "声出すなんて")]
        bottom = [([251, 1665, 284, 1783], "よほど"), ([192, 1680, 237, 1933], "マイケル君との"),
                  ([153, 1667, 186, 1850], "体の相性"), ([102, 1665, 141, 1894], "いーんだねー")]
        items = [{"box": b, "text": t} for b, t in bottom + top]
        text = "".join(it["text"] for it in bm.order_columns(items))
        self.assertEqual(text, "いやー楓さんみたいな人があんな激しい声出すなんて"
                               "よほどマイケル君との体の相性いーんだねー")

    def test_staggered_columns_of_one_sentence_stay_right_to_left(self):
        items = [{"box": [100, 300, 140, 420], "text": "C"}, {"box": [200, 260, 240, 520], "text": "A"},
                 {"box": [150, 280, 190, 470], "text": "B"}]
        self.assertEqual("".join(it["text"] for it in bm.order_columns(items)), "ABC")


class TestOverArt(unittest.TestCase):
    def test_bright_textured_art_is_not_paper(self):
        g = np.full((400, 400), 235, np.uint8)
        rng = np.random.default_rng(1)
        g[:] = np.clip(225 + rng.normal(0, 14, g.shape), 0, 255).astype(np.uint8)  # janela clara com textura
        g[150:250, 120:280] = 160  # letras coloridas
        self.assertTrue(auto_translate.is_text_over_art(g, [120, 150, 280, 250]))

    def test_white_paper_balloon_is_paper(self):
        g = np.full((400, 400), 255, np.uint8)
        for y in range(160, 240, 20):
            g[y:y + 8, 130:270] = 20
        self.assertFalse(auto_translate.is_text_over_art(g, [120, 150, 280, 250]))


class TestRecoverColumn(unittest.TestCase):
    def test_uncovered_column_inside_balloon_is_found(self):
        img = _page()
        cv2.ellipse(img, (400, 500), (160, 230), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(img, (400, 500), (160, 230), 0, 0, 360, (0, 0, 0), 3)
        known, missed = [330, 380, 370, 620], [420, 380, 460, 620]
        for x0, y0, x1, y1 in (known, missed):
            for y in range(y0 + 4, y1 - 10, 40):
                cv2.rectangle(img, (x0 + 4, y), (x1 - 4, y + 30), (90, 30, 20), -1)  # "letras" azuis
        cols = ocr_recover.find_uncovered_columns(img, [known])
        self.assertEqual(len(cols), 1)
        self.assertLess(abs(cols[0][0] - missed[0]), 12)
        found = ocr_recover.recover_blocks(img, [{"box": known}], lambda crop: ("どーしても", 0.99))
        self.assertEqual([f["text"] for f in found], ["どーしても"])
        self.assertEqual(ocr_recover.recover_blocks(img, [{"box": known}], lambda crop: ("ロ", 0.99)), [])


class TestMainLobe(unittest.TestCase):
    def test_single_speech_goes_to_its_lobe(self):
        img = _page()
        for c in [(380, 420), (640, 420)]:
            cv2.ellipse(img, c, (150, 120), 0, 0, 360, (0, 0, 0), 3)
        for c in [(380, 420), (640, 420)]:
            cv2.ellipse(img, c, (147, 117), 0, 0, 360, (255, 255, 255), -1)
        box = [600, 370, 680, 470]
        id_map, infos = bc.build_balloon_map(img)
        info = infos[ba.raw_balloon_id(box, id_map)]
        lobe = bm.main_lobe_info(info, box)
        self.assertLess(lobe["local_mask"].sum(), 0.7 * info["local_mask"].sum())
        reg = bc.compute_safe_text_region(lobe)
        self.assertGreater(reg["safe_cx"], 520)  # centro no lobo da direita, não no pescoço

    def test_plain_oval_is_untouched(self):
        img = _page()
        cv2.ellipse(img, (400, 400), (180, 150), 0, 0, 360, (255, 255, 255), -1)
        cv2.ellipse(img, (400, 400), (180, 150), 0, 0, 360, (0, 0, 0), 3)
        id_map, infos = bc.build_balloon_map(img)
        info = infos[1]
        self.assertIs(bm.main_lobe_info(info, [350, 350, 450, 450]), info)


if __name__ == "__main__":
    unittest.main()
