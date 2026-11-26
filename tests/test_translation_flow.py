"""
test_translation_flow.py - v0.8.1: esperar a cota (em vez de Google literal), contexto entre páginas,
Gemini traduzindo o capítulo inteiro e ordem automática dos motores. IAs simuladas.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import unittest
from unittest import mock

import auto_translate as at
import chapter_context
import chapter_translator
import gemini_text
import quota_wait

CFG = {"gemini_api_keys": ["AIza-teste"], "ollama_host": "http://127.0.0.1:9", "context_pages": 2}


def _bubble(text, x=100, y=100):
    return {"combined_text": text, "box": [x, y, x + 200, y + 120], "lines": [text], "is_vertical": False}


class TestQuotaWait(unittest.TestCase):
    def test_modes_and_when_to_wait(self):
        self.assertEqual(quota_wait.mode({}), "wait")
        self.assertEqual(quota_wait.mode({"quota_fallback": "google"}), "google")
        self.assertTrue(quota_wait.should_wait(CFG, {}))
        self.assertFalse(quota_wait.should_wait({"ollama_host": "http://localhost:11434"}, {}))  # nada configurado
        self.assertTrue(quota_wait.has_any_engine({"ollama_host": "https://abc.trycloudflare.com"}))
        self.assertFalse(quota_wait.should_wait(CFG, {"_quota_wait_started": 0}))  # passou de 12 h

    def test_wait_shows_message_and_frees_engines(self):
        msgs, sleeps = [], []
        eo = {"exhausted_engines": {"groq", "gemini"}, "exhausted_groq_keys": {"k"}, "gemini_text_exhausted": {0},
              "_progress_hook": msgs.append, "_google_announced": True}
        quota_wait.wait_for_quota(eo, sleep=sleeps.append, interval=70, step=30)
        self.assertEqual(sleeps, [30, 30, 10])
        self.assertIn("tentando de novo em 2 min", msgs[0])
        self.assertEqual((eo["exhausted_engines"], eo["exhausted_groq_keys"], eo["gemini_text_exhausted"]), (set(), set(), set()))
        self.assertNotIn("_google_announced", eo)

    def test_stop_button_interrupts_the_wait(self):
        class Stop(BaseException):
            pass

        def hook(msg):
            raise Stop()
        with self.assertRaises(Stop):
            quota_wait.wait_for_quota({"_progress_hook": hook}, sleep=lambda s: None)


class TestRouter(unittest.TestCase):
    MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "{}"}]

    def _eo(self, cfg):
        return {"cfg": cfg, "active_engine": "groq", "exhausted_engines": {"groq", "openrouter", "ollama"}}

    def test_waits_then_translates_with_ai_instead_of_google(self):
        calls = {"gemini": 0}

        def fake_gemini(*a, **k):
            calls["gemini"] += 1
            if calls["gemini"] == 1:
                raise gemini_text.GeminiQuotaExhausted("sem cota")
            return '{"1": "Oi"}'
        real_wait = quota_wait.wait_for_quota
        with mock.patch.object(at.gemini_text, "chat", side_effect=fake_gemini), \
                mock.patch.object(at.quota_wait, "wait_for_quota",
                                  side_effect=lambda eo, r="": real_wait(eo, r, sleep=lambda s: None)) as w, \
                mock.patch.object(at, "google_translate_free") as g, \
                mock.patch.object(at, "check_ollama_available", return_value=(False, None)):
            out = at.execute_translation_request(self.MSGS, engine_opts=self._eo(CFG), is_batch=True,
                                                 dialogue_map={"1": "Hi"})
        self.assertEqual(out, '{"1": "Oi"}')
        self.assertEqual(w.call_count, 1)
        g.assert_not_called()

    def test_google_mode_keeps_old_behaviour(self):
        cfg = dict(CFG, quota_fallback="google")
        with mock.patch.object(at.gemini_text, "chat", side_effect=gemini_text.GeminiQuotaExhausted("x")), \
                mock.patch.object(at, "google_translate_free", return_value="Oi") as g, \
                mock.patch.object(at, "check_ollama_available", return_value=(False, None)):
            out = at.execute_translation_request(self.MSGS, engine_opts=self._eo(cfg), is_batch=True,
                                                 dialogue_map={"1": "Hi"})
        self.assertEqual(json.loads(out), {"1": "Oi"})
        g.assert_called_once()

    def test_gemini_refusal_does_not_mark_it_exhausted(self):
        eo = self._eo(dict(CFG, quota_fallback="google"))
        with mock.patch.object(at.gemini_text, "chat", side_effect=gemini_text.GeminiBlocked("+18")), \
                mock.patch.object(at, "google_translate_free", return_value="Oi"), \
                mock.patch.object(at, "check_ollama_available", return_value=(False, None)):
            at.execute_translation_request(self.MSGS, engine_opts=eo, is_batch=True, dialogue_map={"1": "Hi"})
        self.assertNotIn("gemini", eo["exhausted_engines"])


class TestPageContext(unittest.TestCase):
    def test_block_has_previous_pages_and_respects_limits(self):
        eo = {}
        chapter_context.remember_page(eo, 1, [("WHERE ARE YOU?", "Onde você está?"), ("", "x")])
        chapter_context.remember_page(eo, 2, [("I'M HERE.", "Tô aqui.")])
        block = chapter_context.build_block(eo, {"context_pages": 2}, current_page=3)
        self.assertIn("(pág 1) WHERE ARE YOU? => Onde você está?", block)
        self.assertIn("(pág 2) I'M HERE. => Tô aqui.", block)
        self.assertEqual(chapter_context.build_block(eo, {"context_pages": 0}, current_page=3), "")
        self.assertNotIn("pág 1", chapter_context.build_block(eo, {"context_pages": 1}, current_page=3))
        for i in range(10):
            chapter_context.remember_page(eo, 4 + i, [("X" * 300, "Y" * 300)] * 8)
        self.assertEqual(len(eo["_page_history"]), 3)
        self.assertLess(len(chapter_context.build_block(eo, {}, current_page=99)), chapter_context.MAX_CHARS + 400)

    def test_second_page_prompt_carries_first_page(self):
        prompts = []

        def fake_exec(messages, engine_opts=None, dialogue_map=None, **kw):
            prompts.append(messages[0]["content"])
            pt = {"WHERE IS THE KEY?": "Cadê a chave?", "IN THE DRAWER.": "Na gaveta."}
            return json.dumps({k: pt[v] for k, v in (dialogue_map or {}).items()}, ensure_ascii=False)
        eo = {"cfg": {"context_pages": 2}}
        with mock.patch.object(at, "execute_translation_request", side_effect=fake_exec):
            at.translate_page_dialogue([("WHERE IS THE KEY?", _bubble("WHERE IS THE KEY?"))], engine_opts=eo, page_num=1)
            at.translate_page_dialogue([("IN THE DRAWER.", _bubble("IN THE DRAWER."))], engine_opts=eo, page_num=2)
        self.assertNotIn("CONTEXTO DA CENA", prompts[0])
        self.assertIn("(pág 1) WHERE IS THE KEY? => Cadê a chave?", prompts[1])


class TestChapterTranslator(unittest.TestCase):
    def _pages(self):
        return [{"page": 1, "width": 1200, "height": 1800, "bubbles": [_bubble("WHERE ARE YOU GOING?"), _bubble("HOME.", y=400)]},
                {"page": 2, "width": 1200, "height": 1800, "bubbles": [_bubble("WAIT FOR ME!")]}]

    def test_whole_chapter_in_one_request_fills_cache(self):
        seen = []

        def fake_chat(messages, cfg, state, max_tokens=0, **kw):
            body = json.loads(messages[1]["content"])
            seen.append((messages[0]["content"], body))
            pt = {"WHERE ARE YOU GOING?": "Aonde você vai?", "HOME.": "Pra casa.", "WAIT FOR ME!": "Me espera!"}
            return json.dumps({b["id"]: pt[b["texto"]] for b in body["baloes"]}, ensure_ascii=False)
        cache, eo = {"HOME.": "Pra casa."}, {}
        with mock.patch.object(chapter_translator.gemini_text, "chat", side_effect=fake_chat):
            n = chapter_translator.translate_chapter(self._pages(), cache, CFG, eo, at)
        self.assertEqual(n, 2)
        self.assertEqual(len(seen), 1)  # um pedido só para o capítulo
        self.assertIn("MODO CAPÍTULO", seen[0][0])
        self.assertEqual([(b["pag"], b["texto"]) for b in seen[0][1]["baloes"]],
                         [(1, "WHERE ARE YOU GOING?"), (2, "WAIT FOR ME!")])  # "HOME." já estava no cache
        self.assertEqual(cache["WAIT FOR ME!"], "Me espera!")
        self.assertTrue(eo["_chapter_gemini_used"])

    def test_refused_or_disabled_leaves_pages_to_normal_flow(self):
        cache = {}
        with mock.patch.object(chapter_translator.gemini_text, "chat", side_effect=gemini_text.GeminiBlocked("+18")):
            self.assertEqual(chapter_translator.translate_chapter(self._pages(), cache, CFG, {}, at), 0)
        self.assertEqual(cache, {})
        self.assertFalse(chapter_translator.enabled(dict(CFG, gemini_chapter=False)))
        self.assertFalse(chapter_translator.enabled({}))

    def test_batches_do_not_split_pages(self):
        items = [(p, {"orig_raw": f"{p}-{i}"}) for p in range(1, 6) for i in range(50)]
        batches = list(chapter_translator._batches(items, size=120))
        self.assertTrue(all(len({p for p, _ in b}) == len({p for p, _ in b}) for b in batches))
        for b1, b2 in zip(batches, batches[1:]):
            self.assertNotEqual(b1[-1][0], b2[0][0])
        self.assertEqual(sum(len(b) for b in batches), 250)


class TestAutoOrder(unittest.TestCase):
    def test_auto_uses_local_ai_first_when_it_is_on(self):
        cfg = {"provider": "auto", "groq_api_keys": ["gsk_x"], "ollama_host": "https://abc.trycloudflare.com"}
        with mock.patch.object(at.ollama_client, "list_models", return_value=["qwen3:14b"]), \
                mock.patch.object(at, "check_ollama_available", return_value=(True, "qwen3:14b")), \
                mock.patch.object(at, "_pick_ready_groq_key_and_model") as groq:
            engine, model, eo = at.init_ai_translation_engine(cfg)
        self.assertEqual((engine, model, eo["active_engine"]), ("ollama", "qwen3:14b", "ollama"))
        groq.assert_not_called()

    def test_auto_skips_local_ai_when_off(self):
        cfg = {"provider": "auto", "groq_api_keys": ["gsk_x"]}
        with mock.patch.object(at.ollama_client, "list_models", side_effect=OSError("off")), \
                mock.patch.object(at, "_pick_ready_groq_key_and_model", return_value=("gsk_x", "qwen/qwen3.8-27b", set(), "")):
            engine, _, _ = at.init_ai_translation_engine(cfg)
        self.assertEqual(engine, "groq")


if __name__ == "__main__":
    unittest.main()
