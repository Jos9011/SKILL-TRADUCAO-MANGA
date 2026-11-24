"""
test_lider_capitulo.py - Líder do capítulo: preparo das falas, divisão por cota, leitura da resposta,
anti-invenção, isolamento do motor e orquestração por capítulo.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import ficha_obra
import lider_capitulo as lc


def _resp(personagens=(), termos=()):
    return json.dumps({"personagens": list(personagens), "termos": list(termos)}, ensure_ascii=False)


class TestLines(unittest.TestCase):
    def test_dedupe_trim_and_truncate(self):
        lines = lc.prepare_lines(["林娜！", "林娜", "  olá   mundo ", "!", "", None, "x" * 300])
        self.assertEqual(lines[:2], ["林娜！", "olá mundo"])
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[2].endswith("…"))
        self.assertLessEqual(len(lines[2]), lc.MAX_LINE_LEN + 1)

    def test_split_parts_respects_budget(self):
        lines = ["a" * 100] * 50
        parts, dropped = lc.split_parts(lines, max_chars=1000, max_parts=3)
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(sum(len(l) + 1 for l in p) <= 1000 for p in parts))
        self.assertEqual(dropped, 50 - sum(len(p) for p in parts))
        parts, dropped = lc.split_parts(["oi"], max_chars=1000)
        self.assertEqual((parts, dropped), ([["oi"]], 0))


class TestParse(unittest.TestCase):
    def test_variants(self):
        ok = '<think>hmm {"x":1}</think>```json\n{"personagens":[{"original":"A"}]}\n```'
        self.assertEqual(lc.parse_response(ok)["personagens"], [{"original": "A"}])
        self.assertEqual(lc.parse_response('{"termos": []}'), {"personagens": [], "termos": []})
        for bad in (None, "", "sem json", "{quebrado", "[1,2]", '{"outra": 1}'):
            self.assertIsNone(lc.parse_response(bad), bad)

    def test_grounding_drops_invented_names(self):
        nov = {"personagens": [{"original": "林娜"}, {"original": "张三"}, "lixo"],
               "termos": [{"original": "灵石"}, {"original": "Al"}]}
        out = lc.filter_grounded(nov, ["林娜给我灵石", "all good"])
        self.assertEqual([p["original"] for p in out["personagens"]], ["林娜"])
        self.assertEqual([t["original"] for t in out["termos"]], ["灵石"])


class TestRunLeader(unittest.TestCase):
    def test_merges_across_parts_and_survives_failures(self):
        calls = []

        def call_fn(messages, max_tokens):
            calls.append(messages)
            n = len(calls)
            if n == 1:
                return _resp([{"original": "林娜", "pt": "Lin Na", "genero": "F"}])
            if n == 2:
                raise RuntimeError("413")
            return _resp(termos=[{"original": "灵石", "pt": "pedra espiritual"}])

        lines = ["林娜来了" + "。" * 40] * 1 + [f"第{i}句灵石" + "。" * 40 for i in range(200)]
        ficha = ficha_obra.empty_ficha("X")
        with mock.patch.object(lc, "MAX_CHARS_PER_PART", 2000):
            report, ok = lc.run_leader(lines, ficha, call_fn, obra="X", capitulo="Cap 1", log=lambda *_: None)
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual(ok, len(calls) - 1)
        self.assertEqual(report["personagens_novos"], ["林娜"])
        self.assertEqual(report["termos_novos"], ["灵石"])
        # A ficha já atualizada pela parte 1 é enviada na parte seguinte
        self.assertIn("林娜=Lin Na(F)", calls[1][1]["content"])
        self.assertIn("(parte 1 de", calls[0][1]["content"])

    def test_messages_fit_groq_budget(self):
        ficha = ficha_obra.empty_ficha("X")
        for i in range(150):
            ficha["personagens"].append({"original": f"角色{i}", "pt": f"Personagem {i}", "genero": "?", "nota": ""})
        parts, _ = lc.split_parts(lc.prepare_lines([f"这是第{i}句很长的台词" * 3 for i in range(500)]))
        for part in parts:
            msgs = lc.build_messages(part, ficha, "X", "Cap 1", "zh-CN")
            chars = sum(len(m["content"]) for m in msgs)
            # ~1 token por caractere no pior caso (CJK) + resposta: deve caber em 8k tokens
            self.assertLess(chars + lc.LEADER_MAX_TOKENS, 8000)


class TestCallFn(unittest.TestCase):
    def test_isolates_engine_state_and_uses_leader_model(self):
        engine_opts = {"active_engine": "groq", "preferred_model": "qwen/qwen3.8-27b",
                       "active_model_by_key": {"gsk_abc": "qwen/qwen3.8-27b"},
                       "exhausted_engines": set(), "_fallback_originals": {"x"}}
        seen = {}

        def fake_exec(messages, engine_opts=None, **kw):
            seen.update(engine_opts)
            engine_opts["exhausted_engines"].add("groq")
            engine_opts["active_model_by_key"]["gsk_abc"] = "outro"
            return _resp()

        out = lc.make_call_fn(engine_opts, fake_exec, "openai/gpt-oss-120b")([], 100)
        self.assertEqual(out, _resp())
        self.assertEqual(seen["preferred_model"], "openai/gpt-oss-120b")
        self.assertEqual(engine_opts["exhausted_engines"], set())
        self.assertEqual(engine_opts["active_model_by_key"], {"gsk_abc": "qwen/qwen3.8-27b"})
        self.assertEqual(engine_opts["_fallback_originals"], {"x"})
        self.assertEqual(engine_opts["preferred_model"], "qwen/qwen3.8-27b")

    def test_google_fallback_answer_is_discarded(self):
        def fake_exec(messages, engine_opts=None, **kw):
            engine_opts["_last_used_fallback"] = True
            return "tradução do google"
        self.assertEqual(lc.make_call_fn({}, fake_exec)([], 100), "")

    def test_other_engines_keep_their_model(self):
        seen = {}
        def fake_exec(messages, engine_opts=None, **kw):
            seen.update(engine_opts)
            return ""
        lc.make_call_fn({"active_engine": "ollama", "preferred_model": "m"}, fake_exec)([], 100)
        self.assertEqual(seen["preferred_model"], "m")


class TestRunForChapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cap = os.path.join(self.tmp, "MANGAS", "Minha Obra", "Cap 1")
        os.makedirs(self.cap)
        self.ficha_path = os.path.join(self.tmp, "MANGAS", "Minha Obra", ficha_obra.FICHA_FILENAME)
        self.calls = []
        self.env = mock.patch.dict(os.environ, {"MANGA_FICHA": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake_exec(self, messages, engine_opts=None, **kw):
        self.calls.append(messages)
        return _resp([{"original": "林娜", "pt": "Lin Na", "genero": "F", "nota": "irmã"}])

    def _run(self, **kw):
        args = dict(engine_opts={}, config={}, log=lambda *_: None)
        args.update(kw)
        return lc.run_for_chapter(self.cap, "Cap 1", ["林娜，你好", "早安"], args.pop("engine_opts"),
                                  self.fake_exec, **args)

    def test_full_cycle_saves_in_work_folder(self):
        ctx = self._run()
        self.assertTrue(ctx["changed"])
        self.assertEqual(ctx["path"], self.ficha_path)
        self.assertEqual(ctx["ficha"]["obra"], "Minha Obra")
        self.assertFalse(os.path.exists(self.ficha_path))  # só salva no fim da tradução
        self.assertTrue(lc.save_if_changed(ctx))
        saved = ficha_obra.load_ficha(self.ficha_path)
        self.assertEqual(saved["personagens"][0]["pt"], "Lin Na")
        self.assertEqual(saved["capitulos_lidos"], ["Cap 1"])
        self.assertFalse(lc.save_if_changed(ctx))

    def test_chapter_already_read_skips_call_unless_forced(self):
        lc.save_if_changed(self._run())
        self.calls.clear()
        ctx = self._run()
        self.assertEqual(self.calls, [])
        self.assertFalse(ctx["changed"])
        self.assertEqual(len(ctx["ficha"]["personagens"]), 1)  # ficha salva continua no prompt
        self._run(force=True)
        self.assertEqual(len(self.calls), 1)

    def test_disabled_and_no_ai(self):
        self.assertIsNone(self._run(config={"ficha_obra": False}))
        ctx = self._run(engine_opts=None)
        self.assertEqual(self.calls, [])
        self.assertFalse(ctx["changed"])
        ctx = self._run(config={"lider_capitulo": False})
        self.assertEqual(self.calls, [])
        self.assertIsNotNone(ctx)

    def test_invalid_answer_does_not_mark_chapter(self):
        ctx = lc.run_for_chapter(self.cap, "Cap 1", ["林娜"], {}, lambda *a, **k: "não sei",
                                 config={}, log=lambda *_: None)
        self.assertFalse(ctx["changed"])
        self.assertEqual(ctx["ficha"]["capitulos_lidos"], [])

    def test_leader_model_from_config(self):
        seen = {}
        def fake_exec(messages, engine_opts=None, **kw):
            seen.update(engine_opts)
            return _resp()
        lc.run_for_chapter(self.cap, "Cap 1", ["林娜"], {"active_engine": "groq"}, fake_exec,
                           config={"lider_model": "meu/modelo"}, log=lambda *_: None)
        self.assertEqual(seen["preferred_model"], "meu/modelo")


if __name__ == "__main__":
    unittest.main()
