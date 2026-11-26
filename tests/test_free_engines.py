"""
test_free_engines.py - IA local (Ollama) e Gemini como tradutor (v0.8.1), com servidores falsos.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import io
import json
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import gemini_text
import ollama_client


class FakeOllama(BaseHTTPRequestHandler):
    models = ["llava:7b", "qwen2.5:7b", "qwen3:14b", "dolphin-llama3:8b"]
    requests = []
    reject_think = False

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"models": [{"name": m} for m in self.models]})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.requests.append(data)
        if FakeOllama.reject_think and "think" in data:
            return self._send(400, {"error": "invalid option: think"})
        self._send(200, {"message": {"content": "<think>hmm</think>Eu te disse para não vir sozinho!"},
                         "eval_count": 20, "eval_duration": 1_000_000_000})


class TestOllamaClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), FakeOllama)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.host = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        FakeOllama.requests.clear()
        FakeOllama.reject_think = False
        ollama_client.forget_status()

    def test_pick_model_prefers_current_text_models(self):
        self.assertEqual(ollama_client.pick_model(FakeOllama.models), "qwen3:14b")
        self.assertEqual(ollama_client.pick_model(FakeOllama.models, "dolphin"), "dolphin-llama3:8b")
        self.assertEqual(ollama_client.pick_model(FakeOllama.models, "dolphin-llama3:latest"), "qwen3:14b")
        self.assertEqual(ollama_client.pick_model(["llava:7b"]), "llava:7b")  # só visão: usa o que tem
        self.assertEqual(ollama_client.pick_model(["qwen3:8b", "huihui_ai/qwen3-abliterated:8b"], prefer_uncensored=True),
                         "huihui_ai/qwen3-abliterated:8b")
        self.assertIsNone(ollama_client.pick_model([]))

    def test_chat_sends_context_window_and_no_thinking(self):
        out = ollama_client.chat([{"role": "user", "content": "oi"}], "qwen3:14b", self.host,
                                 cfg={"ollama_num_ctx": 32768})
        self.assertEqual(out, "Eu te disse para não vir sozinho!")  # <think> removido
        sent = FakeOllama.requests[-1]
        self.assertEqual(sent["options"]["num_ctx"], 32768)
        self.assertIs(sent["think"], False)
        self.assertEqual(ollama_client.num_ctx_from({}), 16384)
        self.assertEqual(ollama_client.num_ctx_from({"ollama_num_ctx": "abc"}), 16384)

    def test_old_ollama_without_think_option(self):
        FakeOllama.reject_think = True
        out = ollama_client.chat([{"role": "user", "content": "oi"}], "qwen3:14b", self.host, cfg={})
        self.assertTrue(out)
        self.assertNotIn("think", FakeOllama.requests[-1])

    def test_speed_test_and_status_cache(self):
        res = ollama_client.speed_test(self.host, "qwen3:14b", {})
        self.assertTrue(res["ok"])
        self.assertEqual(res["tok_s"], 20.0)
        self.assertIn("boa", ollama_client.describe_speed(res["tok_s"]))
        self.assertIsNone(ollama_client.cached_status(self.host))
        ollama_client.remember_status(self.host, "", False, True, "qwen3:14b")
        self.assertEqual(ollama_client.cached_status(self.host + "/"), (True, "qwen3:14b"))

    def test_settings_route_reports_model_and_speed(self):
        import importlib
        import os
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "studio"))
        server = importlib.import_module("server")
        client = server.app.test_client()
        d = client.post("/api/test_ollama", json={"host": self.host, "num_ctx": 8192}).get_json()
        self.assertTrue(d["ok"])
        self.assertEqual((d["model"], d["tok_s"]), ("qwen3:14b", 20.0))
        self.assertEqual(FakeOllama.requests[-1]["options"]["num_ctx"], 8192)
        bad = client.post("/api/test_ollama", json={"host": "abc.trycloudflare.com"})
        self.assertEqual(bad.status_code, 400)
        off = client.post("/api/test_ollama", json={"host": "http://127.0.0.1:9"}).get_json()
        self.assertFalse(off["ok"])

    def test_auto_translate_uses_cached_status_without_new_requests(self):
        import auto_translate
        ok, model = auto_translate.check_ollama_available(host=self.host, custom_model="")
        self.assertEqual((ok, model), (True, "qwen3:14b"))
        n = len(FakeOllama.requests)
        self.assertEqual(auto_translate.check_ollama_available(host=self.host, custom_model=""), (True, "qwen3:14b"))
        self.assertEqual(len(FakeOllama.requests), n)  # sem novo aquecimento a cada balão


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(text, reason="STOP"):
    return _Resp(json.dumps({"candidates": [{"finishReason": reason, "content": {"parts": [{"text": text}]}}]}).encode())


def _http(code, msg):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps({"error": {"message": msg}}).encode()))


class TestGeminiText(unittest.TestCase):
    CFG = {"gemini_api_keys": ["AIza-um", "AIza-dois"], "gemini_model": "gemini-3.1-flash-lite"}
    MSGS = [{"role": "system", "content": "Regras"}, {"role": "user", "content": "{\"1\":\"Hi\"}"}]

    def _opener(self, script):
        calls = []

        def op(req, timeout=None):
            calls.append(req.full_url)
            item = script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return op, calls

    def test_payload_moves_system_prompt(self):
        body = gemini_text.to_gemini_payload(self.MSGS + [{"role": "assistant", "content": "ok"}], max_tokens=500)
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "Regras")
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model"])
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 500)

    def test_daily_quota_moves_to_next_key(self):
        op, calls = self._opener([_http(429, "Quota exceeded: requests per day"), _ok('{"1":"Oi"}')])
        state = {}
        out = gemini_text.chat(self.MSGS, self.CFG, state, opener=op, sleep=lambda s: None)
        self.assertEqual(out, '{"1":"Oi"}')
        self.assertIn("AIza-um", calls[0])
        self.assertIn("AIza-dois", calls[1])
        self.assertEqual(state["gemini_text_exhausted"], {0})
        self.assertTrue(gemini_text.has_quota(self.CFG, state))

    def test_per_minute_limit_waits_and_retries_same_key(self):
        waits = []
        op, calls = self._opener([_http(429, "rate limit per minute"), _ok("Oi")])
        out = gemini_text.chat(self.MSGS, self.CFG, {}, opener=op, sleep=waits.append, json_mode=False)
        self.assertEqual((out, waits), ("Oi", [30]))
        self.assertTrue(all("AIza-um" in c for c in calls))

    def test_blocked_content_does_not_burn_key(self):
        blocked = _Resp(json.dumps({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}).encode())
        op, _ = self._opener([blocked])
        state = {}
        with self.assertRaises(gemini_text.GeminiBlocked):
            gemini_text.chat(self.MSGS, self.CFG, state, opener=op)
        self.assertEqual(state.get("gemini_text_exhausted"), set())

    def test_all_keys_exhausted(self):
        op, _ = self._opener([_http(403, "API key not valid"), _http(429, "per day")])
        with self.assertRaises(gemini_text.GeminiQuotaExhausted):
            gemini_text.chat(self.MSGS, self.CFG, {}, opener=op, sleep=lambda s: None)
        self.assertEqual(gemini_text.key_pool({"gemini_api_keys": ["gsk_x", "sk-or-y", " AIza-z "]}), ["AIza-z"])


if __name__ == "__main__":
    unittest.main()
