"""
test_balloon_assign.py - Ligação fala -> balão para a limpeza completa (v0.7.12).
Imagens sintéticas: balão oval alto com pouco texto, balão com duas falas, balões coloridos,
reticências soltas que o OCR não lê e a sombra clara do texto antigo.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import unittest

import cv2
import numpy as np

import balloon_assign as ba
import balloon_cavity as bc
import balloon_color as bcol


def _page(bg=(150, 150, 150)):
    img = np.zeros((1800, 1300, 3), np.uint8)  # tamanho de página real
    img[:] = bg
    return img


def _balloon(img, center, axes, fill=(255, 255, 255)):
    cv2.ellipse(img, center, axes, 0, 0, 360, fill, -1)
    cv2.ellipse(img, center, axes, 0, 0, 360, (0, 0, 0), 3)


def _text(img, box, color=(20, 20, 20)):
    x0, y0, x1, y1 = box
    for y in range(y0 + 4, y1 - 4, 14):
        cv2.putText(img, "WWW", (x0 + 2, y + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)


class TestWhiteBalloons(unittest.TestCase):
    def test_tall_oval_with_short_text_is_accepted(self):
        img = _page()
        _balloon(img, (300, 350), (70, 200))
        box = [260, 300, 340, 400]
        _text(img, box)
        id_map, infos = bc.build_balloon_map(img)
        self.assertGreater(ba.raw_balloon_id(box, id_map), 0)
        self.assertEqual(bc.find_box_balloon_id(box, id_map, infos=infos), 0)  # Trava 5 antiga recusava
        self.assertGreater(ba.assign_balloon_ids([box], id_map, infos)[0], 0)

    def test_two_lines_of_speech_share_the_balloon(self):
        img = _page()
        _balloon(img, (300, 350), (130, 230))
        boxes = [[240, 200, 360, 290], [240, 400, 360, 490]]
        for b in boxes:
            _text(img, b)
        id_map, infos = bc.build_balloon_map(img)
        bids = ba.assign_balloon_ids(boxes, id_map, infos)
        self.assertGreater(bids[0], 0)
        self.assertEqual(bids[0], bids[1])

    def test_huge_white_area_with_tiny_text_is_refused(self):
        img = _page()
        cv2.rectangle(img, (20, 20), (580, 520), (255, 255, 255), -1)
        cv2.rectangle(img, (20, 20), (580, 520), (0, 0, 0), 3)
        box = [290, 260, 320, 275]
        _text(img, box)
        id_map, infos = bc.build_balloon_map(img)
        self.assertEqual(ba.assign_balloon_ids([box], id_map, infos), [0])


class TestColorBalloons(unittest.TestCase):
    def _pink(self, stray=True):
        img = _page((235, 235, 235))
        _balloon(img, (300, 300), (120, 90), fill=(200, 170, 250))  # BGR rosa
        box = [240, 270, 360, 330]
        _text(img, box)
        if stray:  # letra que o OCR não pegou
            cv2.putText(img, "X", (300, 368), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 2)
        return img, box

    def test_pink_balloon_detected_and_fully_cleaned(self):
        img, box = self._pink()
        id_map, infos = bc.build_balloon_map(img)
        self.assertEqual(ba.raw_balloon_id(box, id_map), 0)  # o mapa só vê balões claros
        bids = ba.assign_balloon_ids([box], id_map, infos, img=img)
        self.assertGreater(bids[0], 0)
        info = infos[bids[0]]
        self.assertEqual(info["kind"], "color")
        before = img.copy()
        ba.sweep(img, info)
        inner = img[265:375, 240:360]
        self.assertGreater(int(cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY).min()), 150)  # sem letras
        self.assertTrue(np.array_equal(img[300, 418:424], before[300, 418:424]))  # contorno intacto
        self.assertTrue(np.array_equal(img[:180], before[:180]))  # fora do balão intacto

    def test_dark_or_white_backgrounds_are_left_to_normal_cleaning(self):
        img, box = self._pink(stray=False)
        cv2.ellipse(img, (300, 300), (118, 88), 0, 0, 360, (90, 30, 20), -1)  # azul escuro
        _text(img, box, color=(250, 250, 250))
        self.assertIsNone(bcol.detect_color_balloon(img, box))
        self.assertTrue(bcol.is_plain_white((250, 250, 250)))

    def test_open_color_area_is_refused(self):
        img = _page((200, 170, 250))  # página toda rosa: não é balão fechado
        box = [240, 270, 360, 330]
        _text(img, box)
        self.assertIsNone(bcol.detect_color_balloon(img, box))

    def test_drawing_far_from_text_is_refused(self):
        img, box = self._pink(stray=False)
        box = [255, 300, 345, 335]
        for cx in (235, 365):  # "olhos" escuros longe do texto: rosto, não balão
            cv2.circle(img, (cx, 250), 16, (30, 30, 30), -1)
        self.assertIsNone(bcol.detect_color_balloon(img, box))


class TestEllipsisAndGhost(unittest.TestCase):
    def test_lonely_ellipsis_found_and_added_to_text(self):
        img = _page()
        _balloon(img, (300, 350), (110, 180))
        box = [240, 280, 360, 380]
        _text(img, box)
        for x in (288, 298, 308):
            cv2.circle(img, (x, 405), 2, (0, 0, 0), -1)
        id_map, infos = bc.build_balloon_map(img)
        bid = ba.assign_balloon_ids([box], id_map, infos)[0]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        found = ba.missed_ellipses(gray, infos[bid], [box], line_h=14)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0][0], 298, delta=2)
        self.assertEqual(ba.add_ellipsis("Mas", found[0][1], box), "Mas...")
        self.assertEqual(ba.add_ellipsis("Você", 270, box), "... Você")
        self.assertEqual(ba.add_ellipsis("Mas...", 405, box), "Mas...")

    def test_letters_are_not_taken_for_dots(self):
        img = _page()
        _balloon(img, (300, 350), (110, 180))
        cv2.putText(img, "AB", (280, 420), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        id_map, infos = bc.build_balloon_map(img)
        bid = ba.raw_balloon_id([240, 280, 360, 380], id_map)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        self.assertEqual(ba.missed_ellipses(gray, infos[bid], [[240, 280, 360, 380]], 14), [])

    def test_white_balloon_light_ghost_removed_near_text(self):
        img = _page()
        _balloon(img, (300, 350), (110, 180))
        box = [240, 290, 360, 370]
        img[310:330, 250:350] = (244, 244, 244)  # sombra clara do texto antigo
        img[200:210, 250:350] = (244, 244, 244)  # degradê longe do texto: fica
        id_map, infos = bc.build_balloon_map(img)
        bid = ba.assign_balloon_ids([box], id_map, infos)[0]
        ba.sweep(img, infos[bid], text_boxes=[box])
        self.assertEqual(int(img[310:330, 250:350].min()), 255)
        self.assertEqual(int(img[205, 300, 0]), 244)

    def test_free_width_around(self):
        gray = np.zeros((100, 300), np.uint8)
        gray[:, 100:220] = 255
        self.assertAlmostEqual(ba.free_width_around(gray, 150, 10, 60), 100, delta=2)


class TestSafeRegion(unittest.TestCase):
    def test_profile_is_symmetric_around_text_axis(self):
        img = _page()
        cv2.rectangle(img, (400, 300), (560, 600), (255, 255, 255), -1)
        cv2.rectangle(img, (400, 300), (560, 600), (0, 0, 0), 3)
        cv2.rectangle(img, (300, 470), (444, 700), (150, 150, 150), -1)  # outro quadro cobre o canto
        cv2.rectangle(img, (300, 470), (444, 700), (0, 0, 0), 3)
        id_map, infos = bc.build_balloon_map(img)
        bid = ba.raw_balloon_id([440, 340, 530, 420], id_map)
        reg = bc.compute_safe_text_region(infos[bid])
        cx = reg["safe_cx"]
        for frac, w in reg["band_profile"]:
            if frac >= 0.75:  # parte com recorte: não pode passar da borda do outro quadro (x=446)
                self.assertGreaterEqual(cx - w / 2.0, 447.0, (frac, w, cx))


if __name__ == "__main__":
    unittest.main()
