"""
test_quota_recheck.py - Chaves marcadas "sem cota" voltam a ser tentadas (v0.8.5).

Problema real: o Groq responde TPD "tente de novo em 2 min" quando o pedido passa do que resta;
o sistema marcava a chave/modelo como esgotada até o fim do capítulo. Com a IA local ligada,
a espera de cota (que limpava as marcas) nunca acontecia: o capítulo inteiro ia para a IA local,
lenta, enquanto a tela de Cotas mostrava bastante cota nas chaves.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import unittest
from unittest import mock

import auto_translate
import quota_wait


def _opts(now):
    return {
        "cfg": {"groq_api_keys": ["gsk_AAAAAAAAAAAAAAAA", "gsk_BBBBBBBBBBBBBBBB"], "quota_fallback": "wait"},
        "active_engine": "groq",
        "exhausted_engines": {"groq", "openrouter", "gemini"},
        "exhausted_groq_keys": {"gsk_AAAAAAAAAAAAAAAA", "gsk_BBBBBBBBBBBBBBBB"},
        "exhausted_groq_models": {"gsk_AAAAAAAAAA:qwen/qwen3.8-27b"},
        "groq_auth_failed": {"gsk_BBBBBBBBBBBBBBBB"},
        "_exhausted_since": now - quota_wait.RECHECK_SECS - 1,
    }


class TestRecheck(unittest.TestCase):
    def test_marks_expire_after_recheck_interval_but_bad_keys_stay_out(self):
        opts = _opts(now=1000.0)
        self.assertTrue(quota_wait.maybe_recheck(opts, now=1000.0))
        self.assertEqual(opts["exhausted_engines"], set())
        self.assertEqual(opts["exhausted_groq_models"], set())
        self.assertEqual(opts["exhausted_groq_keys"], {"gsk_BBBBBBBBBBBBBBBB"})  # chave recusada (401) continua fora

    def test_nothing_happens_before_interval(self):
        opts = _opts(now=1000.0)
        opts["_exhausted_since"] = 1000.0 - 10
        self.assertFalse(quota_wait.maybe_recheck(opts, now=1000.0))
        self.assertIn("groq", opts["exhausted_engines"])

    def test_clock_starts_when_something_is_first_marked(self):
        opts = {"exhausted_engines": {"groq"}}
        self.assertFalse(quota_wait.maybe_recheck(opts, now=500.0))
        self.assertEqual(opts["_exhausted_since"], 500.0)
        self.assertTrue(quota_wait.maybe_recheck(opts, now=500.0 + quota_wait.RECHECK_SECS))

    def test_router_goes_back_to_groq_instead_of_local_ai(self):
        opts = _opts(now=quota_wait.time.time())
        calls = []

        def fake_groq(messages, model, key, **kw):
            calls.append(key)
            return "Eu te disse!"

        with mock.patch.object(auto_translate, "query_groq_chat", side_effect=fake_groq), \
                mock.patch.object(auto_translate, "check_ollama_available") as ollama:
            out = auto_translate.execute_translation_request([{"role": "user", "content": "hi"}], engine_opts=opts)
        self.assertEqual(out, "Eu te disse!")
        self.assertEqual(calls, ["gsk_AAAAAAAAAAAAAAAA"])  # a chave recusada não é tentada
        ollama.assert_not_called()
        self.assertTrue(opts["_last_provider_used"].startswith("groq:"))

    def test_auth_error_is_remembered(self):
        opts = {"cfg": {"groq_api_keys": ["gsk_CCCCCCCCCCCCCCCC"]}, "active_engine": "groq", "exhausted_engines": {"openrouter", "gemini", "ollama"}}
        err = auto_translate.GroqRateLimitError("Chave Groq não autorizada (HTTP 401).", is_auth=True)
        with mock.patch.object(auto_translate, "query_groq_chat", side_effect=err), \
                mock.patch.object(quota_wait, "should_wait", return_value=False), \
                mock.patch.object(auto_translate, "google_translate_free", return_value="x"):
            auto_translate.execute_translation_request([{"role": "user", "content": "hi"}], engine_opts=opts)
        self.assertIn("gsk_CCCCCCCCCCCCCCCC", opts["groq_auth_failed"])


if __name__ == "__main__":
    unittest.main()
