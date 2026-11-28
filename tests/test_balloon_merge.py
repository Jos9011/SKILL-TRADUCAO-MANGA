"""
test_balloon_merge.py - Falas do mesmo balão juntas e texto pequeno em balão grande (v0.8.7).

Casos reais das páginas 11-15: colunas japonesas num balão largo saíam traduzidas em pedaços
("KAEDE" / "ESSA AQUI É", "MAS", "I"), e um sussurro pequeno num balão grande ("EU TAMBÉM, IGUAL, W")
era escrito com 9-11 px porque o balão era recusado e valia a caixa OCR.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import unittest

import cv2
import numpy as np

import auto_translate
import balloon_assign as ba
import balloon_cavity as bc
import balloon_merge as bm


def _page():
    img = np.zeros((1800, 1300, 3), np.uint8)
    img[:] = (150, 150, 150)
    return img


def _balloon(img, center, axes):
    cv2.ellipse(img, center, axes, 0, 0, 360, (255, 255, 255), -1)
    cv2.ellipse(img, center, axes, 0, 0, 360, (0, 0, 0), 3)


def _ink(img, box):
    x0, y0, x1, y1 = box
    for y in range(y0 + 4, y1 - 8, 16):
        cv2.rectangle(img, (x0 + 4, y), (x1 - 4, y + 7), (20, 20, 20), -1)


def _bubble(box, text, vertical=True):
    return {"box": list(box), "raw_boxes": [list(box)], "lines": [text], "orig_line_count": 1,
            "combined_text": text, "is_vertical": vertical}


COLUMNS = [[450, 300, 480, 500], [385, 300, 415, 500], [320, 300, 350, 500]]  # direita -> esquerda


def _wide_balloon_with_columns():
    img = _page()
    _balloon(img, (400, 400), (180, 150))
    for c in COLUMNS:
        _ink(img, c)
    return img


class TestMergeSameBalloon(unittest.TestCase):
    def test_single_column_was_refused_alone(self):
        img = _wide_balloon_with_columns()
        id_map, infos = bc.build_balloon_map(img)
        self.assertEqual(bc.find_box_balloon_id(COLUMNS[0], id_map, infos=infos), 0)  # a causa do bug

    def test_columns_become_one_speech_in_reading_order(self):
        img = _wide_balloon_with_columns()
        parts = [_bubble(COLUMNS[2], "かえで"), _bubble(COLUMNS[0], "こちらは"), _bubble(COLUMNS[1], "です")]
        out, joined = bm.merge_same_balloon(parts, img)
        self.assertEqual(joined, 2)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["combined_text"], "こちらはですかえで")  # direita para a esquerda, sem espaço
        self.assertEqual(out[0]["box"], [320, 300, 480, 500])
        self.assertEqual(len(out[0]["raw_boxes"]), 3)

    def test_separate_balloons_stay_separate(self):
        img = _page()
        _balloon(img, (300, 400), (120, 150))
        _balloon(img, (900, 400), (120, 150))
        a, b = [270, 330, 330, 470], [870, 330, 930, 470]
        _ink(img, a)
        _ink(img, b)
        out, joined = bm.merge_same_balloon([_bubble(a, "あ"), _bubble(b, "い")], img)
        self.assertEqual(joined, 0)
        self.assertEqual(len(out), 2)

    def test_korean_lines_keep_spaces(self):
        merged = bm.merge_group([_bubble([0, 0, 50, 10], "안녕", False), _bubble([0, 20, 50, 30], "하세요", False)])
        self.assertEqual(merged["combined_text"], "안녕 하세요")

    def test_ocr_grouping_joins_columns(self):
        img = _wide_balloon_with_columns()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blocks = [{"box": c, "text": t, "lines": [t]} for c, t in zip(COLUMNS, ("こちらは", "です", "かえで"))]
        self.assertEqual(len(auto_translate.smart_group_bubbles(blocks, img_gray=gray)), 1)


def _figure_eight():
    """Dois lobos num contorno só (sem linha no meio), cada um com a sua fala, como na pág 13."""
    img = _page()
    for c in [(380, 420), (640, 420)]:
        cv2.ellipse(img, c, (150, 120), 0, 0, 360, (0, 0, 0), 3)
    for c in [(380, 420), (640, 420)]:
        cv2.ellipse(img, c, (147, 117), 0, 0, 360, (255, 255, 255), -1)
    a, b = [340, 370, 420, 470], [600, 370, 680, 470]
    _ink(img, a)
    _ink(img, b)
    return img, a, b


class TestDoubleBalloon(unittest.TestCase):
    def test_each_lobe_keeps_its_speech(self):
        img, a, b = _figure_eight()
        out, joined = bm.merge_same_balloon([_bubble(a, "のは"), _bubble(b, "たぶん")], img)
        self.assertEqual(joined, 0)

    def test_ocr_grouping_keeps_lobes_apart(self):
        img, a, b = _figure_eight()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blocks = [{"box": a, "text": "のは", "lines": ["のは"]}, {"box": b, "text": "たぶん", "lines": ["たぶん"]}]
        self.assertEqual(len(auto_translate.smart_group_bubbles(blocks, img_gray=gray)), 2)


class TestLayoutBalloon(unittest.TestCase):
    def test_small_whisper_in_big_balloon_uses_the_balloon_for_size(self):
        img = _page()
        _balloon(img, (400, 500), (160, 260))
        box = [370, 470, 430, 530]
        _ink(img, box)
        id_map, infos = bc.build_balloon_map(img)
        bids = ba.assign_balloon_ids([box], id_map, infos)
        self.assertEqual(bids, [0])  # continua sem varredura (segurança)
        lay = ba.layout_balloon_ids([box], id_map, infos, bids, img.shape)
        self.assertGreater(lay[0], 0)
        reg = bc.compute_safe_text_region(infos[lay[0]])
        self.assertGreater(reg["target_w"], 200)  # antes valia a caixa de 60 px

    def test_text_off_center_is_not_moved_into_balloon(self):
        img = _page()
        _balloon(img, (400, 500), (160, 260))
        box = [270, 300, 320, 340]
        _ink(img, box)
        id_map, infos = bc.build_balloon_map(img)
        bids = ba.assign_balloon_ids([box], id_map, infos)
        self.assertEqual(ba.layout_balloon_ids([box], id_map, infos, bids, img.shape), [0])

    def test_balloon_already_assigned_is_untouched(self):
        img = _wide_balloon_with_columns()
        id_map, infos = bc.build_balloon_map(img)
        bids = ba.assign_balloon_ids(COLUMNS, id_map, infos)
        self.assertTrue(all(bids))
        self.assertEqual(ba.layout_balloon_ids(COLUMNS, id_map, infos, bids, img.shape), [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
