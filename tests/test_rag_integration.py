"""
test_rag_integration.py - Garante que o RAG chega ao prompt do Agente 2 e nunca quebra a tradução.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import auto_translate
import rag_memory


def _fake_exec_factory(captured):
    def fake_exec(messages, engine_opts=None, is_adult=True, max_tokens=1024, is_batch=False,
                  dialogue_map=None, src_lang="auto", raise_on_oversize=False):
        captured.append(messages[0]["content"])
        return json.dumps({k: f"Tradução {k}" for k in dialogue_map}, ensure_ascii=False)
    return fake_exec


class TestRagIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mem_path = os.path.join(self.tmp, "memoria_traducoes.json")
        with open(self.mem_path, "w", encoding="utf-8") as f:
            json.dump({"Welcome home, Yu-kun!": "Bem-vindo de volta, Yu-kun!"}, f, ensure_ascii=False)
        rag_memory._CACHE.update(path=None, mtime=None, index=None)
        self.patch_path = mock.patch.object(rag_memory, "DEFAULT_MEMORY_PATH", self.mem_path)
        # build_rag_prompt_block usa DEFAULT_MEMORY_PATH como valor padrão do argumento
        self.patch_func = mock.patch.object(
            rag_memory.build_rag_prompt_block, "__defaults__",
            (self.mem_path, rag_memory.DEFAULT_MAX_CHARS),
        )
        self.patch_path.start()
        self.patch_func.start()

    def tearDown(self):
        self.patch_func.stop()
        self.patch_path.stop()
        rag_memory._CACHE.update(path=None, mtime=None, index=None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_page(self):
        bubbles = [
            ("Welcome home Yu-kun", {"box": [100, 60, 220, 100]}),
            ("Totally different sentence", {"box": [100, 160, 220, 200]}),
        ]
        captured = []
        with mock.patch.object(auto_translate, "execute_translation_request",
                               side_effect=_fake_exec_factory(captured)):
            out = auto_translate.translate_page_dialogue(bubbles, src_lang="en", engine_opts={})
        return out, captured

    def test_similar_memory_reaches_system_prompt(self):
        with mock.patch.dict(os.environ, {"MANGA_RAG": "1"}):
            out, prompts = self._run_page()
        self.assertEqual(len(out), 2)
        self.assertIn("MEMÓRIA DE TRADUÇÕES APROVADAS", prompts[0])
        self.assertIn("Bem-vindo de volta, Yu-kun!", prompts[0])

    def test_disabled_leaves_prompt_unchanged(self):
        with mock.patch.dict(os.environ, {"MANGA_RAG": "0"}):
            out, prompts = self._run_page()
        self.assertEqual(len(out), 2)
        self.assertNotIn("MEMÓRIA DE TRADUÇÕES APROVADAS", prompts[0])

    def test_rag_failure_does_not_break_translation(self):
        with mock.patch.dict(os.environ, {"MANGA_RAG": "1"}), \
                mock.patch.object(rag_memory, "build_rag_prompt_block", side_effect=RuntimeError("boom")):
            out, prompts = self._run_page()
        self.assertEqual(len(out), 2)
        self.assertNotIn("MEMÓRIA DE TRADUÇÕES APROVADAS", prompts[0])

    def test_works_when_module_missing(self):
        with mock.patch.object(auto_translate, "rag_memory", None):
            out, prompts = self._run_page()
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main()
