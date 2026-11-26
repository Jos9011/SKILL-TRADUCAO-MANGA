"""
test_colorizer_merge.py - Como o traço original volta por cima da cor (v0.8.4).
Antes o brilho da cor era trocado pelo da página P&B: a pele (papel branco no mangá) estourava para
branco-amarelado com manchas rosa. Agora a cor do modelo é clareada na direção do papel, com saturação
mais contida, e nunca passa do traço original (Lab): traço preto fica preto, a sombra e o tom de pele do modelo ficam.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import tempfile
import unittest
from unittest import mock

import numpy as np

import manga_colorizer


class TestLineartMerge(unittest.TestCase):
    def test_paper_white_keeps_model_skin_tone(self):
        color = np.full((8, 8, 3), (150, 190, 235), np.uint8)  # BGR pêssego
        gray = np.full((8, 8), 255, np.uint8)  # papel branco na página original
        out = manga_colorizer.merge_lineart(color, gray)
        b, g, r = (int(v) for v in out[0, 0])
        self.assertGreater(r, b + 40)  # continua pêssego, não estoura para branco
        self.assertLess(b, 215)
        self.assertGreaterEqual(b, 150)  # e fica um pouco mais clara que a cor crua

    def test_black_ink_stays_black(self):
        color = np.full((8, 8, 3), (150, 190, 235), np.uint8)
        gray = np.zeros((8, 8), np.uint8)
        out = manga_colorizer.merge_lineart(color, gray)
        self.assertLess(int(out.max()), 20)

    def test_gray_screentone_darkens_but_keeps_hue(self):
        color = np.full((8, 8, 3), (60, 60, 220), np.uint8)  # vermelho
        gray = np.full((8, 8), 90, np.uint8)
        out = manga_colorizer.merge_lineart(color, gray)
        b, g, r = (int(v) for v in out[0, 0])
        self.assertGreater(r, g + 30)  # continua avermelhado
        self.assertLess(r, 220)  # mas mais escuro

    def test_screentone_dots_become_smooth_shading(self):
        # Retícula (pontinhos pretos isolados no papel) marcava pele molhada e céu: virava hematoma e granulado
        gray = np.full((80, 1500), 255, np.uint8)  # faixa de uma página de 1500 px (a suavização escala com isso)
        gray[::3, ::3] = 0
        color = np.full((80, 1500, 3), (150, 190, 235), np.uint8)
        out = manga_colorizer.merge_lineart(color, gray)[10:70, 100:1400].astype(int)
        self.assertLess(max(float(out[:, :, c].std()) for c in range(3)), 4)  # sombra lisa, sem pontos
        self.assertGreater(int(out[:, :, 2].min()), 120)  # nenhum ponto preto sobrou

    def test_real_line_stays_sharp_next_to_screentone(self):
        gray = np.full((80, 1500), 255, np.uint8)
        gray[::3, ::3] = 0
        gray[:, 30:32] = 0  # traço de 2 px
        color = np.full((80, 1500, 3), (150, 190, 235), np.uint8)
        out = manga_colorizer.merge_lineart(color, gray)
        self.assertLess(int(out[20:40, 30:32].max()), 25)


class TestModelDownload(unittest.TestCase):
    def test_interrupted_download_leaves_no_fake_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "m.onnx")

            def broken(url, path):
                with open(path, "wb") as f:
                    f.write(b"x" * (12 * 1024 * 1024))  # 12 MB e a conexão cai
                raise OSError("conexão perdida")

            with mock.patch("urllib.request.urlretrieve", side_effect=broken):
                with self.assertRaises(OSError):
                    manga_colorizer.download_model_if_needed(dest, verbose=False)
            self.assertFalse(os.path.exists(dest))
            self.assertEqual(os.listdir(tmp), [])


if __name__ == "__main__":
    unittest.main()
