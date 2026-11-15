"""
tests/test_colorizer.py - Testes unitários para o módulo manga_colorizer e endpoints de colorização.
Regra de Ouro: Arquivo coeso e enxuto (< 300 linhas).
"""

import os
import unittest
import tempfile
import shutil
import numpy as np
import cv2
from PIL import Image

import manga_colorizer
from studio import server
import auto_translate


class MangaColorizerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="manga_test_colorizer_")
        # Cria 2 imagens de teste em preto e branco
        cls.img1_path = os.path.join(cls.test_dir, "01.jpg")
        cls.img2_path = os.path.join(cls.test_dir, "02.png")

        img1 = np.full((128, 96, 3), 200, dtype=np.uint8)
        img1[40:80, 30:70] = 30  # quadrado escuro (arte / linha)
        cv2.imwrite(cls.img1_path, img1)

        img2 = np.full((96, 128), 240, dtype=np.uint8)
        img2[20:60, 40:80] = 10
        cv2.imwrite(cls.img2_path, img2)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_dir):
            shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_natural_sort_key(self):
        filenames = ["p10.jpg", "p2.jpg", "p1.jpg", "p20.jpg"]
        sorted_files = sorted(filenames, key=manga_colorizer.natural_sort_key)
        self.assertEqual(sorted_files, ["p1.jpg", "p2.jpg", "p10.jpg", "p20.jpg"])

    def test_colorize_cv2_returns_valid_rgb(self):
        img = np.full((64, 64, 3), 180, dtype=np.uint8)
        img[20:44, 20:44] = 0  # nanquim
        res = manga_colorizer.colorize_cv2(img, max_size=64, preserve_lineart=True)
        self.assertEqual(res.shape, (64, 64, 3))
        self.assertEqual(res.dtype, np.uint8)
        # Nanquim central deve ser preservado escuro devido ao preserve_lineart
        self.assertLessEqual(int(res[30, 30, 0]), 20)

    def test_colorize_image_file_and_pil(self):
        # Testa arquivo
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
            out_path = tf.name
        try:
            res_path = manga_colorizer.colorize_image(
                self.img1_path, output_path=out_path, max_size=64
            )
            self.assertEqual(res_path, out_path)
            self.assertTrue(os.path.exists(out_path))
            self.assertGreater(os.path.getsize(out_path), 500)
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

        # Testa PIL Image
        pil_in = Image.open(self.img2_path)
        pil_out = manga_colorizer.colorize_image(pil_in, max_size=64)
        self.assertIsInstance(pil_out, Image.Image)
        self.assertEqual(pil_out.size, pil_in.size)

    def test_colorize_manga_folder_batch(self):
        progress_events = []

        def dummy_progress(stage, current, total, text, result=None):
            progress_events.append((stage, current, total))

        res = manga_colorizer.colorize_manga_folder(
            self.test_dir, progress_cb=dummy_progress, max_size=64
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("total_pages"), 2)
        out_dir = res.get("output_dir")
        self.assertTrue(os.path.isdir(out_dir))
        out_files = [f for f in os.listdir(out_dir) if f.lower().endswith(".jpg")]
        self.assertEqual(len(out_files), 2)
        self.assertIn(("done", 2, 2), progress_events)
        shutil.rmtree(out_dir, ignore_errors=True)

    def test_api_colorize_endpoint(self):
        client = server.app.test_client()
        resp = client.post(
            "/api/colorize",
            json={
                "path": self.test_dir,
                "colorize": True,
                "colorize_only": True,
            },
        )
        self.assertIn(resp.status_code, (200, 409))
        data = resp.get_json()
        if resp.status_code == 200:
            self.assertTrue(data.get("success"))

    def test_process_manga_signature_and_defaults(self):
        import inspect

        sig = inspect.signature(auto_translate.process_manga)
        self.assertIn("colorize", sig.parameters)
        self.assertIsNone(sig.parameters["colorize"].default)
        self.assertIn("color_reference", sig.parameters)

    def test_color_reference_profile_and_transfer(self):
        import color_reference

        # Test with colored image
        colored_ref = np.full((64, 64, 3), (120, 80, 200), dtype=np.uint8)
        profile = color_reference.extract_reference_profile(colored_ref)
        self.assertIsNotNone(profile)
        self.assertIn("mean_a", profile)
        self.assertIn("mean_b", profile)

        # Test transfer on a colored image
        dummy_in = np.full((64, 64, 3), 150, dtype=np.uint8)
        transferred = color_reference.apply_reference_transfer(dummy_in, profile, strength=0.9)
        self.assertEqual(transferred.shape, (64, 64, 3))
        self.assertTrue(np.any(transferred[30, 30] != dummy_in[30, 30]))

        # Test transfer with strength=0 (zero modification, 100% reversible!)
        unmodified = color_reference.apply_reference_transfer(dummy_in, profile, strength=0.0)
        np.testing.assert_array_equal(dummy_in, unmodified)

    def test_colorize_with_reference_param(self):
        colored_ref = np.full((64, 64, 3), (120, 80, 200), dtype=np.uint8)
        img_gray = np.full((64, 64, 3), 180, dtype=np.uint8)
        res_with_ref = manga_colorizer.colorize_cv2(img_gray, max_size=64, reference=colored_ref)
        self.assertEqual(res_with_ref.shape, (64, 64, 3))


if __name__ == "__main__":
    unittest.main()
