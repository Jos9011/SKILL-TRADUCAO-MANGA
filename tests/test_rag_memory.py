"""
test_rag_memory.py - Testes da Memória de Tradução por Semelhança (RAG leve)
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import rag_memory
from rag_memory import (
    TranslationMemoryIndex,
    build_rag_prompt_block,
    get_index,
    normalize_text,
    retrieve_examples,
    tokenize,
)

SAMPLE_MEMORY = {
    "早安": "bom dia",
    "早安～": "bom dia~",
    "謝謝": "obrigado",
    "大哥哥": "irmãozinho",
    "大哥哥：": "irmãozinho:",
    "同事給的巧克力": "o chocolate do colega",
    "ARE YOU STARING AT MY BOOBS?": "TÁ OLHANDO PROS MEUS PEITOS?",
    "Welcome home, Yu-kun!": "Bem-vindo de volta, Yu-kun!",
    "선배, 안녕하세요": "Oi, veterano",
    "lixo": "<x id=1> MYMEMORY WARNING",
}


class RagMemoryBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.mem_path = os.path.join(self.tmp, "memoria_traducoes.json")
        self._write(SAMPLE_MEMORY)
        rag_memory._CACHE.update(path=None, mtime=None, index=None)
        self.env = mock.patch.dict(os.environ, {"MANGA_RAG": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, data):
        with open(self.mem_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


class TestTokenizer(unittest.TestCase):
    def test_normalize_strips_punctuation_and_case(self):
        self.assertEqual(normalize_text("大哥哥～♡！"), "大哥哥")
        self.assertEqual(normalize_text("  Hello,   WORLD!! "), "hello world")

    def test_cjk_bigrams(self):
        terms = tokenize("早安")
        self.assertIn("早", terms)
        self.assertIn("早安", terms)

    def test_latin_words_and_trigrams(self):
        terms = tokenize("Boobs")
        self.assertIn("w:boobs", terms)
        self.assertIn("t:#bo", terms)

    def test_empty(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("!!!～♡"), [])


class TestIndexSearch(RagMemoryBase):
    def test_finds_similar_not_only_identical(self):
        idx = get_index(self.mem_path)
        hits = idx.search("早安！！")
        self.assertTrue(hits)
        self.assertEqual(hits[0][1].rstrip("~"), "bom dia")

    def test_tolerates_ocr_noise_in_latin(self):
        idx = get_index(self.mem_path)
        hits = idx.search("ARE Y0U STARING AT MY B00BS")
        self.assertEqual(hits[0][0], "ARE YOU STARING AT MY BOOBS?")

    def test_korean(self):
        hits = get_index(self.mem_path).search("선배!")
        self.assertEqual(hits[0][1], "Oi, veterano")

    def test_unrelated_query_returns_nothing(self):
        self.assertEqual(get_index(self.mem_path).search("火車站在哪裡"), [])
        self.assertEqual(get_index(self.mem_path).search("spaceship engine"), [])

    def test_bad_translations_are_not_indexed(self):
        idx = get_index(self.mem_path)
        self.assertNotIn("lixo", [d[0] for d in idx.docs])

    def test_empty_or_missing_memory(self):
        self.assertEqual(len(TranslationMemoryIndex([])), 0)
        self.assertEqual(retrieve_examples(["早安"], path=os.path.join(self.tmp, "nao_existe.json")), [])

    def test_corrupted_json_does_not_crash(self):
        with open(self.mem_path, "w", encoding="utf-8") as f:
            f.write("{ isso não é json")
        self.assertEqual(retrieve_examples(["早安"], path=self.mem_path), [])
        self.assertEqual(build_rag_prompt_block(["早安"], path=self.mem_path), "")


class TestCacheRefresh(RagMemoryBase):
    def test_index_rebuilds_when_file_changes(self):
        self.assertEqual(get_index(self.mem_path).search("晚安"), [])
        time.sleep(0.02)
        data = dict(SAMPLE_MEMORY, 晚安囉="boa noite")
        self._write(data)
        os.utime(self.mem_path, (time.time() + 5, time.time() + 5))
        hits = get_index(self.mem_path).search("晚安")
        self.assertEqual(hits[0][1], "boa noite")


class TestRetrieveAndPrompt(RagMemoryBase):
    def test_punctuation_variants_deduplicated(self):
        ex = retrieve_examples(["大哥哥♡"], path=self.mem_path)
        origs = [o for o, _ in ex]
        self.assertEqual(len([o for o in origs if normalize_text(o) == "大哥哥"]), 1)

    def test_max_examples_respected(self):
        ex = retrieve_examples(["早安", "謝謝", "大哥哥", "선배"], path=self.mem_path, max_examples=2)
        self.assertEqual(len(ex), 2)

    def test_prompt_block_format_and_size(self):
        block = build_rag_prompt_block(["早安", "大哥哥"], path=self.mem_path, max_chars=400)
        self.assertIn("MEMÓRIA DE TRADUÇÕES APROVADAS", block)
        self.assertIn('"bom dia', block)
        self.assertLessEqual(len(block), 400)

    def test_prompt_block_empty_when_no_match(self):
        self.assertEqual(build_rag_prompt_block(["spaceship engine"], path=self.mem_path), "")

    def test_disabled_by_env(self):
        with mock.patch.dict(os.environ, {"MANGA_RAG": "0"}):
            self.assertEqual(build_rag_prompt_block(["早安"], path=self.mem_path), "")

    def test_disabled_by_config(self):
        cfg = os.path.join(self.tmp, "config.json")
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"rag_memory": False}, f)
        with mock.patch.dict(os.environ, {"MANGA_RAG": ""}), \
                mock.patch.object(rag_memory, "_CONFIG_PATHS", (cfg,)):
            self.assertFalse(rag_memory.is_enabled())
            self.assertEqual(build_rag_prompt_block(["早安"], path=self.mem_path), "")

    def test_enabled_by_default_without_config(self):
        with mock.patch.dict(os.environ, {"MANGA_RAG": ""}), \
                mock.patch.object(rag_memory, "_CONFIG_PATHS", (os.path.join(self.tmp, "x.json"),)):
            self.assertTrue(rag_memory.is_enabled())

    def test_internal_error_never_propagates(self):
        with mock.patch.object(rag_memory, "retrieve_examples", side_effect=RuntimeError("boom")):
            self.assertEqual(build_rag_prompt_block(["早安"], path=self.mem_path), "")


if __name__ == "__main__":
    unittest.main()
