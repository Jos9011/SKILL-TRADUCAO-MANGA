"""
test_typography_narrow.py - Quadros de narração estreitos e altos não podem virar uma linha só.
Medidas reais (largura x altura úteis) de quadros de "Toshiue no Kuro Gal Doukyuusei Ch.1".
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import unittest

from PIL import Image, ImageDraw

import auto_translate
import typography_ptbr as tp

PAGE_W = 1353


def _flat(w):
    return [(i / 8.0, float(w)) for i in range(9)]


class TestNarrowBoxes(unittest.TestCase):
    def setUp(self):
        self.draw = ImageDraw.Draw(Image.new("L", (10, 10)))
        self.font_path = auto_translate.select_font_for_bubble("TEXTO")

    def _fit(self, text, w, h, band=None):
        font, lines, line_h = tp.fit_text_ptbr(self.draw, text, w, h, self.font_path,
                                               measure_fn=auto_translate.measure_manga_line_width,
                                               stroke_width=0, band_profile=band, page_w=PAGE_W)
        widths = [auto_translate.measure_manga_line_width(self.draw, l, font, 0) for l in lines]
        return font, lines, line_h, max(widths) if widths else 0

    def test_long_narration_in_tall_narrow_box(self):
        text = ("COMO HERDEIRO DE UM CONGLOMERADO, ME COLOCARAM EM UMA CÂMARA DE SONO "
                "CRIOGÊNICO DE ÚLTIMA GERAÇÃO.")
        font, lines, line_h, max_w = self._fit(text, 104, 364, _flat(104))
        self.assertGreater(len(lines), 8)          # antes: 1 linha atravessando a página
        self.assertLessEqual(max_w, 104)
        self.assertGreaterEqual(font.size, 13)
        self.assertLessEqual(len(lines) * line_h, 364)
        self.assertEqual(" ".join(lines).replace("- ", "").replace("-", ""), text.replace("-", ""))

    def test_very_narrow_box_uses_hyphenation(self):
        font, lines, line_h, max_w = self._fit("E DEPOIS PASSARAM DEZ ANOS.", 58, 220, _flat(58))
        self.assertGreater(len(lines), 3)
        self.assertLessEqual(max_w, 58)

    def test_last_resort_never_exceeds_box_width(self):
        text = "UMA FALA BEM LONGA QUE NÃO CABE DE JEITO NENHUM NESTE BALÃO PEQUENO DEMAIS PARA ELA"
        font, lines, line_h, max_w = self._fit(text, 60, 40)
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(max_w, 60)
        self.assertGreaterEqual(font.size, 9)

    def test_tapering_box_respects_narrow_part(self):
        band = [(0.0, 164), (0.125, 172), (0.25, 172), (0.375, 172), (0.5, 172),
                (0.625, 138), (0.75, 96), (0.875, 46), (1.0, 46)]
        font, lines, line_h, max_w = self._fit("E MINHA FAMÍLIA SE ESPALOU, NINGUÉM SABE ONDE ESTÃO",
                                               172, 277, band)
        self.assertLessEqual(max_w, 130)

    def test_normal_bubbles_unchanged(self):
        font, lines, _, _ = self._fit("VOCÊ ACORDOU DE UM SONO MUITO LONGO", 140, 120)
        self.assertEqual(lines, ["VOCÊ ACORDOU", "DE UM SONO", "MUITO LONGO"])
        font, lines, _, _ = self._fit("SIM!", 80, 60)
        self.assertEqual(lines, ["SIM!"])

    def test_hard_wrap_helper(self):
        f = tp.ImageFont.truetype(self.font_path, 11)
        lines = tp.wrap_hard_ptbr(self.draw, "SUPERCALIFRAGILISTICO OI", f, 50,
                                  auto_translate.measure_manga_line_width)
        self.assertTrue(all(auto_translate.measure_manga_line_width(self.draw, l, f, 0) <= 50 for l in lines))
        self.assertEqual("".join(lines).replace("-", "").replace(" ", ""), "SUPERCALIFRAGILISTICOOI")


if __name__ == "__main__":
    unittest.main()
