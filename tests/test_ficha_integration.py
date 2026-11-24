"""
test_ficha_integration.py - Garante que a Ficha da Obra chega ao prompt do Agente 2, que o Líder
roda entre o OCR e a tradução no process_manga, e que nada disso quebra a tradução.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image

import auto_translate
import ficha_obra
import lider_capitulo


def _ficha():
    f = ficha_obra.empty_ficha("Obra")
    f["personagens"].append({"original": "Yu-kun", "pt": "Yu-kun", "genero": "M", "nota": "filho"})
    return f


class TestPromptWiring(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"MANGA_RAG": "0"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _run_page(self, **kw):
        bubbles = [("Welcome home Yu-kun", {"box": [100, 60, 220, 100]}),
                   ("Totally different sentence", {"box": [100, 160, 220, 200]})]
        prompts = []

        def fake_exec(messages, engine_opts=None, dialogue_map=None, **k):
            prompts.append(messages[0]["content"])
            return json.dumps({key: f"Tradução {key}" for key in dialogue_map}, ensure_ascii=False)

        with mock.patch.object(auto_translate, "execute_translation_request", side_effect=fake_exec):
            out = auto_translate.translate_page_dialogue(bubbles, src_lang="en", engine_opts={}, **kw)
        return out, prompts

    def test_ficha_reaches_system_prompt(self):
        out, prompts = self._run_page(ficha=_ficha())
        self.assertEqual(len(out), 2)
        self.assertIn("FICHA DA OBRA", prompts[0])
        self.assertIn("- Yu-kun -> Yu-kun (homem): filho", prompts[0])

    def test_without_ficha_prompt_is_unchanged(self):
        _, with_none = self._run_page()
        _, with_empty = self._run_page(ficha=ficha_obra.empty_ficha())
        self.assertNotIn("FICHA DA OBRA", with_none[0])
        self.assertEqual(with_none, with_empty)

    def test_ficha_failure_does_not_break_translation(self):
        with mock.patch.object(ficha_obra, "build_prompt_block", side_effect=RuntimeError("boom")):
            out, prompts = self._run_page(ficha=_ficha())
        self.assertEqual(len(out), 2)
        self.assertNotIn("FICHA DA OBRA", prompts[0])

    def test_ficha_and_rag_together(self):
        with mock.patch.object(auto_translate, "rag_memory") as rag:
            rag.build_rag_prompt_block.return_value = "\nMEMÓRIA DE TRADUÇÕES APROVADAS:\n- \"a\" -> \"b\"\n"
            _, prompts = self._run_page(ficha=_ficha())
        self.assertLess(prompts[0].index("FICHA DA OBRA"), prompts[0].index("MEMÓRIA DE TRADUÇÕES"))


class TestProcessMangaFlow(unittest.TestCase):
    """Roda o process_manga de verdade com OCR e IA simulados."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.obra = os.path.join(self.tmp, "Obra Teste")
        self.cap = os.path.join(self.obra, "Cap 1")
        self.out = os.path.join(self.tmp, "saida")
        os.makedirs(self.cap)
        os.makedirs(self.out)
        for i in (1, 2):
            Image.new("RGB", (800, 1200), "white").save(os.path.join(self.cap, f"{i:03d}.png"))
        self.events = []
        self.env = mock.patch.dict(os.environ, {"MANGA_RAG": "0", "MANGA_FICHA": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_ocr(self, manga_dir, out_path, **kw):
        self.events.append("ocr")
        pages = []
        texts = [["Welcome home, Yu-kun!"], ["Yu-kun, are you okay?"]]
        for i, lines in enumerate(texts, 1):
            pages.append({"img_path": f"{i:03d}.png", "img_width": 800, "img_height": 1200,
                          "blocks": [{"box": [200, 200, 600, 360], "lines": lines, "vertical": False}]})
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"version": "rapidocr", "pages": pages}, f)

    def fake_exec(self, messages, engine_opts=None, dialogue_map=None, **kw):
        if messages[0]["content"] == lider_capitulo.SYSTEM_PROMPT:
            self.events.append("lider")
            self.leader_input = messages[1]["content"]
            return json.dumps({"personagens": [{"original": "Yu-kun", "pt": "Yu-kun", "genero": "M",
                                                "nota": "filho"}], "termos": []})
        self.events.append("traducao")
        self.translator_prompts.append(messages[0]["content"])
        return json.dumps({k: "Bem-vindo, Yu-kun!" for k in (dialogue_map or {})}, ensure_ascii=False)

    def _process(self, config_extra=None):
        self.translator_prompts = []
        cfg = {"translated_mangas_dir": self.out, "colorize": False}
        cfg.update(config_extra or {})
        engine = ("groq", "qwen/qwen3.8-27b", {"active_engine": "groq", "cfg": cfg})
        with mock.patch.object(auto_translate, "generate_rapidocr_json", side_effect=self.fake_ocr), \
                mock.patch.object(auto_translate, "init_ai_translation_engine", return_value=engine), \
                mock.patch.object(auto_translate, "execute_translation_request", side_effect=self.fake_exec), \
                mock.patch.object(auto_translate, "lookup_translation_memory", return_value=None), \
                mock.patch.object(auto_translate, "update_global_translation_memory"), \
                mock.patch.object(auto_translate, "translate_single_dialogue", return_value=""), \
                mock.patch.object(auto_translate, "google_translate_free", side_effect=lambda t, **k: t):
            return auto_translate.process_manga(self.cap, ocr_mode="rapidocr", config=cfg, retranslate=True)

    def test_leader_runs_after_ocr_and_before_translation(self):
        self._process()
        self.assertEqual(self.events[0], "ocr")
        self.assertEqual(self.events[1], "lider")
        self.assertIn("traducao", self.events[2:])
        self.assertEqual(self.events.count("lider"), 1)
        # O Líder recebeu as falas das DUAS páginas numa única leitura
        self.assertIn("Welcome home, Yu-kun!", self.leader_input)
        self.assertIn("Yu-kun, are you okay?", self.leader_input)
        # A novidade do Líder já entrou no prompt do tradutor neste mesmo capítulo
        self.assertTrue(any("Yu-kun -> Yu-kun (homem)" in p for p in self.translator_prompts))
        saved = ficha_obra.load_ficha(os.path.join(self.obra, ficha_obra.FICHA_FILENAME))
        self.assertEqual(saved["obra"], "Obra Teste")
        self.assertEqual(saved["capitulos_lidos"], ["Cap 1"])
        self.assertEqual(saved["personagens"][0]["genero"], "M")

    def test_disabled_in_config_skips_everything(self):
        self._process({"ficha_obra": False})
        self.assertNotIn("lider", self.events)
        self.assertFalse(os.path.exists(os.path.join(self.obra, ficha_obra.FICHA_FILENAME)))
        self.assertTrue(all("FICHA DA OBRA" not in p for p in self.translator_prompts))

    def test_leader_crash_does_not_stop_translation(self):
        with mock.patch.object(lider_capitulo, "run_for_chapter", side_effect=RuntimeError("boom")):
            self._process()
        self.assertIn("traducao", self.events)
        self.assertNotIn("lider", self.events)


if __name__ == "__main__":
    unittest.main()
