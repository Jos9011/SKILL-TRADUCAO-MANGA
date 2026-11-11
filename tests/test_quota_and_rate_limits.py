# -*- coding: utf-8 -*-
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import auto_translate
from studio import server


class _FakeHTTPResponse:
    def __init__(self, body_obj, headers=None, status=200):
        raw = body_obj if isinstance(body_obj, str) else json.dumps(body_obj)
        self._bytes = raw.encode("utf-8")
        self.headers = headers or {}
        self.status = status

    def read(self):
        return self._bytes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_http_error(url, code, body_obj, headers=None):
    raw = body_obj if isinstance(body_obj, str) else json.dumps(body_obj)
    return urllib.error.HTTPError(
        url=url,
        code=code,
        msg=f"HTTP {code}",
        hdrs=headers or {},
        fp=io.BytesIO(raw.encode("utf-8")),
    )


class QuotaAndRateLimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.quota_file = os.path.join(self.tmp_dir.name, "quota_state.json")
        self.patch_qf = mock.patch.object(auto_translate, "QUOTA_STATE_FILE", self.quota_file)
        self.patch_qf.start()

    def tearDown(self):
        self.patch_qf.stop()
        self.tmp_dir.cleanup()

    def test_prompt_compression_and_en_rule_filtering(self):
        p_en = auto_translate.build_dual_engine_system_prompt(is_adult=True, src_lang="en")
        p_ja = auto_translate.build_dual_engine_system_prompt(is_adult=True, src_lang="ja")
        p_ko = auto_translate.build_dual_engine_system_prompt(is_adult=True, src_lang="ko")

        self.assertLess(len(p_en), 4200)
        self.assertLess(len(p_ja), 3200)
        self.assertLess(len(p_ko), 3400)

        # Essential rules kept
        for kw in ("buceta", "pau", "gozar", "estranha", "O papai", "Yu-kun", "JSON"):
            self.assertIn(kw, p_en)

        # No broken CJK / dangling header leakage on generic English
        self.assertNotIn("Nomes de personagens e termos fixos:", p_en)
        self.assertNotIn("Gyaru tatuada", p_en)
        self.assertNotIn("Cold~", p_en)
        self.assertNotIn("badugi", p_en.lower())

        dos_gen, donts_gen = auto_translate.load_learning_rules(src_lang="en")
        self.assertTrue(any("Come hang out" in r for r in dos_gen + donts_gen))
        self.assertFalse(any("Gyaru tatuada" in r for r in dos_gen + donts_gen))
        self.assertFalse(any("Cold~" in r for r in dos_gen + donts_gen))
        self.assertFalse(any("badugi" in r.lower() for r in dos_gen + donts_gen))

        # Work-matched English preserves that specific work's glossary without leaking other works
        dos_work, donts_work = auto_translate.load_learning_rules(src_lang="en", active_work_hint="Misaki Boku no Toshiue")
        self.assertTrue(any("Yu-kun" in r for r in dos_work + donts_work))
        self.assertFalse(any("In Which a Slave" in r for r in dos_work + donts_work))

    def test_parse_groq_rate_limit_details(self):
        err_tpd = (
            "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
            "`qwen/qwen3.8-27b` on tokens per day (TPD): Limit 200000, Used 197930, "
            "Requested 3968. Please try again in 13m39.9s.'}}"
        )
        det = auto_translate.parse_groq_rate_limit_details(err_tpd, http_code=429)
        self.assertEqual(det["limit_type"], "TPD")
        self.assertEqual(det["limit"], 200000)
        self.assertEqual(det["used"], 197930)
        self.assertEqual(det["requested"], 3968)
        self.assertEqual(det["remaining"], 2070)
        self.assertAlmostEqual(det["retry_after"], 13 * 60 + 39.9, places=1)
        self.assertTrue(det["is_daily"])
        self.assertFalse(det["is_oversize"])

        err_413 = "Request entity too large: TPM Limit 8000, Requested 9200. Reduce your message."
        det_413 = auto_translate.parse_groq_rate_limit_details(err_413, http_code=413)
        self.assertTrue(det_413["is_oversize"])
        self.assertFalse(det_413["is_daily"])

        err_rpd = "Rate limit reached on requests per day (RPD): Limit 1000, Used 1000."
        det_rpd = auto_translate.parse_groq_rate_limit_details(err_rpd, http_code=429)
        self.assertEqual(det_rpd["limit_type"], "RPD")
        self.assertTrue(det_rpd["is_daily"])

    def test_groq_leaky_bucket_and_ping_vs_page_ready(self):
        fake_key = "gsk_testkey_alpha_1234567890"
        model = "qwen/qwen3.8-27b"
        t0 = 1_700_000_000.0
        err_tpd = (
            "Rate limit reached on tokens per day (TPD): Limit 200000, Used 197930, "
            "Requested 3968. Please try again in 13m39.9s."
        )
        with mock.patch("time.time", return_value=t0):
            auto_translate.record_groq_error(fake_key, model, 429, err_tpd)
            # Small 14-token ping passes right after
            auto_translate.record_groq_response_headers(
                fake_key,
                model,
                {
                    "x-ratelimit-remaining-requests": "950",
                    "x-ratelimit-limit-requests": "1000",
                    "x-ratelimit-remaining-tokens": "7986",
                    "x-ratelimit-limit-tokens": "8000",
                },
                used_tokens=14,
                source="ping",
            )
            snap_soon = auto_translate.get_groq_quota_snapshot(fake_key, model, now_ts=t0 + 1.0)

        self.assertTrue(snap_soon["tpd_exhausted"])
        self.assertFalse(snap_soon["page_ready"])
        self.assertGreater(snap_soon["tpd_reset_sec"], 0.0)

        # Even if ping HTTP call would succeed, telemetry keeps check_groq_available blocked
        with mock.patch("time.time", return_value=t0 + 2.0):
            ok_chk, msg_chk = auto_translate.check_groq_available(fake_key, model, check_telemetry=True)
        self.assertFalse(ok_chk)
        self.assertIn("TPD", msg_chk)

        # After 25 minutes (~3472 tokens drained + 2070 = 5542 > GROQ_MIN_PAGE_TOKENS), recovered!
        snap_later = auto_translate.get_groq_quota_snapshot(fake_key, model, now_ts=t0 + 1500.0)
        self.assertFalse(snap_later["tpd_exhausted"])
        self.assertTrue(snap_later["page_ready"])
        self.assertGreater(snap_later["tpd_remaining"], auto_translate.GROQ_MIN_PAGE_TOKENS)

    def test_query_groq_chat_isolation_and_oversize(self):
        k1 = "gsk_firstkey_1111111111"
        k2 = "gsk_secondkey_2222222222"
        messages = [{"role": "user", "content": "Hello"}]
        engine_opts = {
            "groq_api_keys": [k1, k2],
            "exhausted_groq_models": set(),
            "active_model_by_key": {},
            "groq_model_cooldowns": {},
        }

        calls = []

        def fake_urlopen(req, timeout=45):
            auth = req.headers.get("Authorization", "")
            body = json.loads(req.data.decode("utf-8"))
            m = body["model"]
            calls.append((auth, m))
            if k1 in auth and m == "qwen/qwen3.8-27b":
                raise _make_http_error(
                    req.full_url,
                    429,
                    "tokens per day (TPD): Limit 200000, Used 198500, Requested 2500. Please try again in 8m0s.",
                )
            return _FakeHTTPResponse(
                {
                    "choices": [{"message": {"content": f"ok:{m}"}}],
                    "usage": {"total_tokens": 500},
                },
                headers={"x-ratelimit-remaining-requests": "900", "x-ratelimit-remaining-tokens": "7000"},
            )

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res1 = auto_translate.query_groq_chat(
                messages,
                "qwen/qwen3.8-27b",
                k1,
                fallback_model="openai/gpt-oss-120b",
                engine_opts=engine_opts,
            )
            self.assertEqual(res1, "ok:openai/gpt-oss-120b")
            self.assertEqual(engine_opts["active_model_by_key"].get(k1[:12]), "openai/gpt-oss-120b")
            self.assertIn(f"{k1[:12]}:qwen/qwen3.8-27b", engine_opts["exhausted_groq_models"])
            self.assertNotIn("qwen/qwen3.8-27b", engine_opts["exhausted_groq_models"])

            # Key 2 MUST still run qwen/qwen3.8-27b untouched!
            res2 = auto_translate.query_groq_chat(
                messages,
                "qwen/qwen3.8-27b",
                k2,
                fallback_model="openai/gpt-oss-120b",
                engine_opts=engine_opts,
            )
            self.assertEqual(res2, "ok:qwen/qwen3.8-27b")

        # Oversize 413 must NOT ban models
        exh_before = set()
        opts_oversize = {"exhausted_groq_models": exh_before}

        def fake_413(req, timeout=45):
            raise _make_http_error(
                req.full_url, 413, "Request entity too large: TPM Limit 8000, Requested 9500"
            )

        with mock.patch("urllib.request.urlopen", side_effect=fake_413):
            with self.assertRaises(auto_translate.GroqRateLimitError) as ctx:
                auto_translate.query_groq_chat(
                    messages, "qwen/qwen3.8-27b", k2, engine_opts=opts_oversize
                )
        self.assertTrue(ctx.exception.is_oversize)
        self.assertEqual(exh_before, set())

    def test_translate_page_dialogue_chunking_and_413_split(self):
        # 24 bubbles -> should split cleanly into 3 chunks (10, 10, 4) with compact keys
        bubbles_24 = [
            (f"Hello line {i}!", {"box": [100, i * 60, 220, i * 60 + 40]})
            for i in range(1, 25)
        ]
        captured_payloads = []

        def fake_exec(messages, engine_opts=None, is_adult=True, max_tokens=1024, is_batch=False, dialogue_map=None, src_lang="auto", raise_on_oversize=False):
            payload = json.loads(messages[1]["content"])
            captured_payloads.append(payload)
            return json.dumps({k: f"Olá linha {k}!" for k in dialogue_map}, ensure_ascii=False)

        with mock.patch.object(auto_translate, "execute_translation_request", side_effect=fake_exec):
            out = auto_translate.translate_page_dialogue(bubbles_24, src_lang="en", engine_opts={})

        self.assertEqual(len(captured_payloads), 3)
        self.assertEqual([len(p["baloes"]) for p in captured_payloads], [10, 10, 4])
        self.assertEqual(captured_payloads[0]["ordem"], "RTL")
        self.assertIn("texto", captured_payloads[0]["baloes"][0])
        self.assertEqual(len(out), 24)

        # Recursive 413 half-splitting: 8 bubbles -> raises oversize once -> splits into 4 + 4
        bubbles_8 = [
            (f"Sentence {i}?", {"box": [100, i * 80, 220, i * 80 + 40]})
            for i in range(1, 9)
        ]
        seen_sizes = []

        def fake_exec_split(messages, engine_opts=None, is_adult=True, max_tokens=1024, is_batch=False, dialogue_map=None, src_lang="auto", raise_on_oversize=False):
            sz = len(dialogue_map)
            seen_sizes.append(sz)
            if sz == 8 and raise_on_oversize:
                raise auto_translate.GroqRateLimitError("HTTP 413 oversize", is_oversize=True)
            return json.dumps({k: f"Frase {k}?" for k in dialogue_map}, ensure_ascii=False)

        with mock.patch.object(auto_translate, "execute_translation_request", side_effect=fake_exec_split):
            out_split = auto_translate.translate_page_dialogue(bubbles_8, src_lang="en", engine_opts={})

        self.assertEqual(seen_sizes, [8, 4, 4])
        self.assertEqual(len(out_split), 8)
        self.assertTrue(all(v.startswith("Frase ") for v in out_split.values()))

    def test_openrouter_net_credits_and_upstream_vs_daily(self):
        or_key = "sk-or-v1-test-openrouter-0001"

        def fake_check(req, timeout=10):
            if req.full_url.endswith("/auth/key"):
                return _FakeHTTPResponse({"data": {"is_free_tier": True, "free_model_daily_requests": {"used": 50, "limit": 50, "remaining": 0}}})
            if req.full_url.endswith("/credits"):
                return _FakeHTTPResponse({"data": {"total_credits": 10.0, "total_usage": 10.0}})
            raise AssertionError(f"Unexpected URL {req.full_url}")

        with mock.patch("urllib.request.urlopen", side_effect=fake_check):
            ok, rem, msg = auto_translate.check_openrouter_key_status(or_key, "nvidia/nemotron-3.5-lightning:free")
        self.assertFalse(ok)
        self.assertEqual(rem, 0)
        self.assertIn("esgotada", msg.lower())

        # Upstream 429 switches model on the same key without killing key
        opts = {"openrouter_exhausted_keys": set(), "openrouter_exhausted_models": set(), "cfg": {}}

        def fake_chat(req, timeout=45):
            body = json.loads(req.data.decode("utf-8"))
            m = body["model"]
            if m == "nvidia/nemotron-3.5-lightning:free":
                raise _make_http_error(req.full_url, 429, "Upstream provider temporarily rate-limited")
            return _FakeHTTPResponse({"choices": [{"message": {"content": "Tradução via fallback"}}]})

        with mock.patch("urllib.request.urlopen", side_effect=fake_chat):
            reply = auto_translate.query_openrouter_chat(
                [{"role": "user", "content": "hi"}],
                "nvidia/nemotron-3.5-lightning:free",
                api_key=or_key,
                api_keys=[or_key],
                engine_opts=opts,
            )
        self.assertEqual(reply, "Tradução via fallback")
        self.assertNotIn(0, opts["openrouter_exhausted_keys"])
        snap_or = auto_translate.get_openrouter_quota_snapshot(or_key)
        self.assertEqual(snap_or.get("upstream_429_model"), "nvidia/nemotron-3.5-lightning:free")

    def test_gemini_vision_telemetry_and_dashboard(self):
        gem1 = "AIzaSyTestGeminiKey00001"
        gem2 = "AIzaSyTestGeminiKey00002"
        cfg = {
            "gemini_api_keys": [gem1, gem2],
            "gemini_model": "gemini-2.5-flash",
            "groq_api_keys": [],
            "openrouter_api_keys": [],
        }
        opts = {}

        def fake_gem(req, timeout=60):
            if gem1 in req.full_url:
                raise _make_http_error(req.full_url, 429, "Quota exceeded for quota metric per day (free_tier)")
            return _FakeHTTPResponse({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": '{"1": "Oi"}'}]}}]})

        with mock.patch("urllib.request.urlopen", side_effect=fake_gem):
            txt = auto_translate.query_gemini_vision("QUFBQQ==", "ocr", cfg, engine_opts=opts)

        self.assertEqual(txt, '{"1": "Oi"}')
        snap1 = auto_translate.get_gemini_quota_snapshot(gem1)
        self.assertTrue(snap1.get("quota_exhausted"))
        self.assertTrue(snap1.get("quota_is_daily"))

    def test_flask_status_and_test_key(self):
        fake_cfg = {
            "groq_api_keys": ["gsk_testflask_1111111111", "gsk_testflask_2222222222"],
            "groq_model": "qwen/qwen3.8-27b",
            "groq_fallback_model": "openai/gpt-oss-120b",
            "openrouter_api_keys": ["sk-or-v1-flask-0000001"],
            "gemini_api_keys": ["AIzaSyFlaskGemini00001"],
            "gemini_model": "gemini-2.5-flash",
            "ollama_host": "http://127.0.0.1:19999",
        }

        def fake_urlopen(req, timeout=8):
            url = req.full_url
            if "api.groq.com" in url:
                auth = req.headers.get("Authorization", "")
                if "1111111111" in auth:
                    body = json.loads(req.data.decode("utf-8"))
                    txt_content = body["messages"][0]["content"]
                    # Probe has long text; ping has "ping"
                    if len(txt_content) > 100 and body["model"] == "qwen/qwen3.8-27b":
                        raise _make_http_error(
                            url,
                            429,
                            "Rate limit reached on tokens per day (TPD): Limit 200000, Used 198900, Requested 1950. Please try again in 7m55.2s.",
                        )
                    return _FakeHTTPResponse(
                        {"choices": [{"message": {"content": "pong"}}], "usage": {"total_tokens": 12}},
                        headers={
                            "x-ratelimit-remaining-requests": "980",
                            "x-ratelimit-limit-requests": "1000",
                            "x-ratelimit-remaining-tokens": "7980",
                            "x-ratelimit-limit-tokens": "8000",
                        },
                    )
                # Key 2 connection error -> must NOT produce fake 1000 / 8000!
                raise RuntimeError("Simulated offline timeout")

            if "openrouter.ai/api/v1/credits" in url:
                return _FakeHTTPResponse({"data": {"total_credits": 5.0, "total_usage": 5.0}})
            if "openrouter.ai/api/v1/auth/key" in url:
                return _FakeHTTPResponse({"data": {"is_free_tier": True}})

            if "generativelanguage.googleapis.com" in url:
                if ":generateContent" in url:
                    raise _make_http_error(url, 429, "You exceeded your current quota, per_day limit.")
                return _FakeHTTPResponse({"models": [{"name": "models/gemini-2.5-flash"}]})

            raise urllib.error.URLError("offline")

        client = server.app.test_client()
        with mock.patch.object(auto_translate, "load_config", return_value=fake_cfg), \
             mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            # 1. /api/test_key on Groq active model detects TPD exhaustion despite ping OK
            r_tk_groq = client.post("/api/test_key", json={
                "provider": "groq",
                "key": fake_cfg["groq_api_keys"][0],
                "model": "qwen/qwen3.8-27b",
                "deep": True,
            })
            d_tk_groq = r_tk_groq.get_json()
            self.assertFalse(d_tk_groq["valid"])
            self.assertTrue(d_tk_groq["tpd_exhausted"])
            self.assertTrue(d_tk_groq["is_daily_limit"])

            # 2. /api/test_key on Gemini detects 429 on generateContent even though /models is 200
            r_tk_gem = client.post("/api/test_key", json={
                "provider": "gemini",
                "key": fake_cfg["gemini_api_keys"][0],
                "model": "gemini-2.5-flash",
                "deep": True,
            })
            d_tk_gem = r_tk_gem.get_json()
            self.assertFalse(d_tk_gem["valid"])
            self.assertTrue(d_tk_gem["quota_exhausted"])

            # 3. /api/status (standard telemetry-aware poll) reflects both runtime failures!
            r_st = client.get("/api/status")
            self.assertEqual(r_st.status_code, 200)
            st = r_st.get_json()

            k1_qwen = st["groq"]["keys"][0]["models"]["qwen/qwen3.8-27b"]
            self.assertFalse(k1_qwen["ok"])
            self.assertFalse(k1_qwen["page_ready"])
            self.assertTrue(k1_qwen["tpd_exhausted"])
            self.assertEqual(st["groq"]["ready_keys_count"], 0)
            # Key 1 still has fallback GPT-OSS-120B ready
            self.assertEqual(st["groq"]["any_model_ready_keys"], 1)

            # Key 2 errored -> NO fake 1000 / 8000
            k2_qwen = st["groq"]["keys"][1]["models"]["qwen/qwen3.8-27b"]
            self.assertFalse(k2_qwen["ok"])
            self.assertIsNone(k2_qwen["rem_req"])
            self.assertIsNone(k2_qwen["rem_tok"])

            # OpenRouter net credits == 0.0 (5.0 - 5.0), no fake free_quota
            or_k = st["openrouter"]["keys"][0]
            self.assertEqual(or_k["credits"], 0.0)
            self.assertFalse(or_k["has_free_quota_details"])

            # Gemini shows runtime 429 exhausted
            gem_k = st["gemini"]["keys"][0]
            self.assertFalse(gem_k["ok"])
            self.assertTrue(gem_k["quota_exhausted"])
            self.assertGreater(len(st["runtime_warnings"]), 0)


if __name__ == "__main__":
    unittest.main()
