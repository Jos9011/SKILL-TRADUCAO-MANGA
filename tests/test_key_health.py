"""
test_key_health.py - Falha passageira não marca a chave como "sem cota" (v0.8.6).

Problema real: um timeout ou um 503 do Groq fazia o roteador marcar TODAS as chaves como sem cota
(2 chaves = 13 pedidos, 3 chaves = 19 pedidos para um lote só) e o capítulo ia para o Google literal,
enquanto a tela de Cotas mostrava saldo. Só 429 diário e 401/403 podem tirar a chave da fila.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import io
import json
import socket
import unittest
import urllib.error
from unittest import mock

import auto_translate
import gemini_text
import key_health

KEYS = ["gsk_AAAAAAAAAAAAAAAA", "gsk_BBBBBBBBBBBBBBBB", "gsk_CCCCCCCCCCCCCCCC"]


def _http(code, body):
    return urllib.error.HTTPError("https://api.groq.com", code, "err", {}, io.BytesIO(body.encode("utf-8")))


class _Ok:
    def __init__(self, text):
        self._raw = json.dumps({"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 50}}).encode()
        self.headers = {}
        self.status = 200

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opts(fallback="google"):
    cfg = {"groq_api_keys": list(KEYS), "quota_fallback": fallback}
    return {"cfg": cfg, "groq_api_keys": list(KEYS), "active_engine": "groq", "api_key": KEYS[0]}


class _Base(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(auto_translate.time, "sleep", lambda s: None),
            mock.patch.object(auto_translate, "record_groq_error", lambda *a, **k: None),
            mock.patch.object(auto_translate, "record_groq_response_headers", lambda *a, **k: None),
            mock.patch.object(auto_translate, "google_translate_free", lambda t, source_lang=None: "GOOGLE"),
            mock.patch.object(auto_translate, "check_ollama_available", lambda **k: (False, None)),
            mock.patch.object(key_health, "SHORT_WAIT", 0),  # a espera curta real é de 1 min
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_router(self, side_effect, opts=None):
        calls = []

        def fake(req, timeout=None):
            calls.append(req)
            return side_effect(len(calls))

        opts = opts or _opts()
        with mock.patch("urllib.request.urlopen", fake):
            out = auto_translate.execute_translation_request([{"role": "user", "content": "oi"}], engine_opts=opts)
        return out, opts, calls


class TestTransientDoesNotExhaust(_Base):
    def test_timeout_on_every_key_keeps_keys_and_retries_shortly(self):
        def boom(n):
            raise socket.timeout("timed out")
        out, opts, calls = self.run_router(boom)
        self.assertEqual(opts.get("exhausted_groq_keys", set()), set())
        self.assertNotIn("groq", opts.get("exhausted_engines", set()))
        # Timeout não é repetido no mesmo modelo: no máximo 2 modelos por chave em cada rodada
        rounds = 1 + key_health.MAX_SHORT_WAITS
        self.assertLessEqual(len(calls), len(KEYS) * key_health.MAX_TRANSIENT_MODELS * rounds)

    def test_503_then_recovers_without_google(self):
        def flaky(n):
            if n <= 6:
                raise _http(503, '{"error":{"message":"Service Unavailable"}}')
            return _Ok("Olá!")
        out, opts, _ = self.run_router(flaky)
        self.assertEqual(out, "Olá!")
        self.assertEqual(opts.get("exhausted_groq_keys", set()), set())
        self.assertNotEqual(opts.get("_last_provider_used"), "google_fallback")

    def test_generic_400_does_not_burn_model(self):
        def bad(n):
            if n == 1:
                raise _http(400, '{"error":{"message":"Please reduce the length of the messages"}}')
            return _Ok("Certo.")
        out, opts, _ = self.run_router(bad)
        self.assertEqual(out, "Certo.")
        self.assertEqual(opts.get("exhausted_groq_models", set()), set())


class TestRealLimitsStillExhaust(_Base):
    def test_429_daily_marks_keys(self):
        body = ('{"error":{"message":"Rate limit reached on tokens per day (TPD): Limit 200000, '
                'Used 199500, Requested 2500. Please try again in 7m26.4s."}}')

        def daily(n):
            raise _http(429, body)
        out, opts, _ = self.run_router(daily)
        self.assertEqual(out, "GOOGLE")
        self.assertEqual(opts["exhausted_groq_keys"], set(KEYS))

    def test_401_marks_key_as_auth_failed(self):
        def auth(n):
            raise _http(401, '{"error":{"message":"Invalid API Key"}}')
        out, opts, _ = self.run_router(auth)
        self.assertEqual(opts["groq_auth_failed"], set(KEYS))


class TestHelpers(unittest.TestCase):
    def test_model_gone_only_for_clear_messages(self):
        self.assertTrue(key_health.is_model_gone(404, ""))
        self.assertTrue(key_health.is_model_gone(400, "The model `x` has been decommissioned"))
        self.assertFalse(key_health.is_model_gone(400, '{"error":{"message":"model output must be json"}}'))

    def test_bench_moves_key_to_end(self):
        opts = {}
        key_health.bench_key(opts, KEYS[0], secs=20, now=100.0)
        self.assertTrue(key_health.is_benched(opts, KEYS[0], now=110.0))
        self.assertFalse(key_health.is_benched(opts, KEYS[0], now=121.0))


class TestSingleDialogueBudget(unittest.TestCase):
    def test_same_text_back_costs_one_request(self):
        calls = []

        def fake_exec(messages, **kw):
            calls.append(1)
            return "TOKITO"
        with mock.patch.object(auto_translate, "execute_translation_request", fake_exec), \
                mock.patch.object(auto_translate, "google_translate_free", lambda t, source_lang=None: "TOKITO"):
            auto_translate.translate_single_dialogue("TOKITO", engine_opts={}, is_adult=True)
        self.assertEqual(len(calls), 1)

    def test_refusal_still_gets_neutral_retry(self):
        answers = iter(["Desculpe, não posso ajudar com isso.", "Vamos embora daqui agora!"])
        calls = []

        def fake_exec(messages, **kw):
            calls.append(1)
            return next(answers)
        with mock.patch.object(auto_translate, "execute_translation_request", fake_exec), \
                mock.patch.object(auto_translate, "is_valid_translation", lambda o, t: "Vamos" in t):
            out = auto_translate.translate_single_dialogue("Let's get out of here now!", engine_opts={}, is_adult=True)
        self.assertEqual(len(calls), 2)
        self.assertIn("Vamos", out)


class TestGeminiTransient(unittest.TestCase):
    def test_503_does_not_mark_key(self):
        state = {}

        def opener(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 503, "overloaded", {}, io.BytesIO(b"model is overloaded"))
        with self.assertRaises(gemini_text.GeminiTransient):
            gemini_text.chat([{"role": "user", "content": "oi"}], {"gemini_api_keys": ["AIzaX"]}, state,
                             opener=opener, sleep=lambda s: None)
        self.assertEqual(state["gemini_text_exhausted"], set())


if __name__ == "__main__":
    unittest.main()
