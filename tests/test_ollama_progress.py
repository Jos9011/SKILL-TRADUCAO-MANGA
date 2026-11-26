"""
test_ollama_progress.py - IA local lenta (v0.8.3): o registro mostra que ela está trabalhando,
quanto do modelo está na placa de vídeo e quanto tempo cada resposta levou.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import contextlib
import io
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import ollama_client


class SlowStreamingOllama(BaseHTTPRequestHandler):
    """Responde em streaming (como o Ollama de verdade) depois de 'delay' segundos lendo o pedido."""
    delay = 0.0
    size_vram = 2_000_000_000
    size = 4_000_000_000
    mid_stream_error = False

    def log_message(self, *a):
        pass

    def do_GET(self):
        body = json.dumps({"models": [{"name": "qwen3:4b", "model": "qwen3:4b",
                                       "size": self.size, "size_vram": self.size_vram}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        time.sleep(self.delay)  # "lendo" o prompt (no processador isso demora)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        if not data.get("stream"):
            self.wfile.write(json.dumps({"message": {"content": "tudo"}, "done": True}).encode())
            return
        for piece in ("<think></think>", "Eu te ", "disse!"):
            self.wfile.write((json.dumps({"message": {"content": piece}, "done": False}) + "\n").encode())
            self.wfile.flush()
        if self.mid_stream_error:
            self.wfile.write((json.dumps({"error": "model runner has unexpectedly stopped"}) + "\n").encode())
            return
        self.wfile.write((json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 2900,
                                      "eval_count": 310, "eval_duration": 41_900_000_000}) + "\n").encode())


class TestOllamaProgress(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), SlowStreamingOllama)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.host = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        SlowStreamingOllama.delay = 0.0
        SlowStreamingOllama.size_vram = 2_000_000_000
        SlowStreamingOllama.mid_stream_error = False
        ollama_client.forget_status()

    def _chat(self, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            out = ollama_client.chat([{"role": "user", "content": "oi"}], "qwen3:4b", self.host, cfg={}, **kw)
        return out, buf.getvalue()

    def test_streamed_answer_is_joined_and_cleaned(self):
        out, log = self._chat()
        self.assertEqual(out, "Eu te disse!")
        self.assertEqual(log, "")  # sem 'label' (aquecimento, teste): não escreve nada

    def test_slow_answer_prints_heartbeat_and_summary(self):
        SlowStreamingOllama.delay = 0.35
        old = ollama_client.HEARTBEAT_SECS
        ollama_client.HEARTBEAT_SECS = 0.1
        try:
            out, log = self._chat(label="qwen3:4b")
        finally:
            ollama_client.HEARTBEAT_SECS = old
        self.assertEqual(out, "Eu te disse!")
        self.assertIn("[IA local] qwen3:4b traduzindo", log)
        self.assertIn("ainda trabalhando", log)
        self.assertIn("respondeu em", log)
        self.assertIn("2900", log)
        self.assertIn("7.4 tokens/s", log)

    def test_error_inside_stream_is_raised(self):
        SlowStreamingOllama.mid_stream_error = True
        with self.assertRaises(RuntimeError) as ctx:
            self._chat()
        self.assertIn("unexpectedly stopped", str(ctx.exception))

    def test_gpu_share_and_warning(self):
        share = ollama_client.gpu_share(self.host, "qwen3:4b")
        self.assertAlmostEqual(share, 0.5)
        self.assertIn("50% do modelo ficou no processador", ollama_client.describe_placement("qwen3:4b", share))
        SlowStreamingOllama.size_vram = SlowStreamingOllama.size
        self.assertIn("100% na placa de vídeo",
                      ollama_client.describe_placement("qwen3:4b", ollama_client.gpu_share(self.host, "qwen3:4b")))
        self.assertIsNone(ollama_client.gpu_share(self.host, "outro:7b"))
        self.assertEqual(ollama_client.describe_placement("x", None), "")

    def test_cache_ignores_adult_flag_when_model_is_fixed(self):
        ollama_client.remember_status(self.host, "qwen3:4b", True, True, "qwen3:4b")
        self.assertEqual(ollama_client.cached_status(self.host, "qwen3:4b", False), (True, "qwen3:4b"))
        self.assertIsNone(ollama_client.cached_status(self.host, "", False))


class TestQwen3NoThinking(unittest.TestCase):
    """Qwen3 ignorava "think": false e gastava os 350 tokens do balão raciocinando (1 min por balão)."""

    def test_qwen3_gets_no_think_switch_without_touching_caller_messages(self):
        msgs = [{"role": "system", "content": "Regras"}, {"role": "user", "content": "{}"}]
        sent = ollama_client._payload(msgs, "qwen3:4b", 0.0, 350, 8192)["messages"]
        self.assertTrue(sent[0]["content"].endswith("/no_think"))
        self.assertEqual(sent[1]["content"], "{}")
        self.assertEqual(msgs[0]["content"], "Regras")  # lista original intacta
        only_user = ollama_client._payload([{"role": "user", "content": "oi"}], "qwen3:8b", 0.0, 1, 8192)["messages"]
        self.assertTrue(only_user[-1]["content"].endswith("/no_think"))

    def test_other_models_unchanged(self):
        msgs = [{"role": "system", "content": "Regras"}]
        self.assertEqual(ollama_client._payload(msgs, "gemma3:4b", 0.0, 1, 8192)["messages"], msgs)

    def test_unfinished_thinking_is_dropped(self):
        self.assertEqual(ollama_client.clean_answer("<think>Okay, let me tackle this"), "")
        self.assertEqual(ollama_client.clean_answer("<think>\n\n</think>\n\nEu te disse!"), "Eu te disse!")
        self.assertEqual(ollama_client.clean_answer("Eu te disse!"), "Eu te disse!")


if __name__ == "__main__":
    unittest.main()
