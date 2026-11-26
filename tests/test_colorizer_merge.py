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

import cv2
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


class TestChromaConsolidation(unittest.TestCase):
    """Moletom rosa->roxo->azul e saia jeans com manchas de várias cores: uma peça, uma cor."""

    def test_blotchy_garment_becomes_one_color(self):
        rng = np.random.default_rng(7)
        lab = np.zeros((300, 600, 3), np.float32)
        lab[:, :, 0] = 150
        lab[:, :300, 1:] = (150, 110)  # moletom roxo
        lab[:, 300:, 1:] = (140, 150)  # pele
        noise = cv2.GaussianBlur(rng.normal(0, 1, (300, 600, 2)).astype(np.float32), (0, 0), 6)
        noise *= 10.0 / noise.std()  # manchas largas com ~10 de desvio em a/b
        lab[:, :, 1:] += noise  # o modelo espalha tons rosados/azulados dentro da mesma área
        img = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_Lab2BGR)
        out = manga_colorizer.consolidate_colors(img)
        ab_in = cv2.cvtColor(img, cv2.COLOR_BGR2Lab)[:, 20:280, 1:].reshape(-1, 2).astype(float)
        ab_out = cv2.cvtColor(out, cv2.COLOR_BGR2Lab)[:, 20:280, 1:].reshape(-1, 2).astype(float)
        self.assertLess(ab_out.std(axis=0).max(), ab_in.std(axis=0).max() * 0.9)  # na página real: -20 a -27%

    def test_different_colors_stay_separate_and_light_is_kept(self):
        img = np.zeros((100, 200, 3), np.uint8)
        img[:, :100] = (60, 60, 220)  # vermelho
        img[:, 100:] = (220, 120, 40)  # azul
        img[:50] = (img[:50] * 0.6).astype(np.uint8)  # sombra
        out = manga_colorizer.consolidate_colors(img)
        self.assertGreater(int(out[75, 20, 2]), int(out[75, 20, 0]) + 100)
        self.assertGreater(int(out[75, 180, 0]), int(out[75, 180, 2]) + 100)
        l_in = cv2.cvtColor(img, cv2.COLOR_BGR2Lab)[:, :, 0].astype(int)
        l_out = cv2.cvtColor(out, cv2.COLOR_BGR2Lab)[:, :, 0].astype(int)
        self.assertLess(int(np.abs(l_in - l_out).max()), 3)  # sombras do modelo continuam


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
