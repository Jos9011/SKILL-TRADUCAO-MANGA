"""
test_app_paths.py - Pasta de código x pasta de dados (base do .exe da v0.8.0) e botão Encerrar.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import app_paths


class TestDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_running_from_source_keeps_project_folder(self):
        self.assertFalse(app_paths.FROZEN)
        with mock.patch.dict(os.environ, {"MANGA_STUDIO_DATA": ""}):
            self.assertEqual(app_paths._default_data_dir(), app_paths.CODE_DIR)
        self.assertEqual(app_paths.prepare(), [])  # mesma pasta: nada a copiar

    def test_env_var_and_frozen_default(self):
        with mock.patch.dict(os.environ, {"MANGA_STUDIO_DATA": self.tmp}):
            self.assertEqual(app_paths._default_data_dir(), os.path.abspath(self.tmp))
        with mock.patch.object(app_paths, "FROZEN", True), \
                mock.patch.dict(os.environ, {"MANGA_STUDIO_DATA": "", "APPDATA": self.tmp}):
            self.assertEqual(app_paths._default_data_dir(), os.path.join(self.tmp, "MangaStudio"))

    def _fake_install(self):
        home = os.path.join(self.tmp, "home")
        old = os.path.join(home, "OneDrive", "Documentos", "SISTEMA DE TRADUÇÃO")
        os.makedirs(old)
        open(os.path.join(old, "auto_translate.py"), "w").close()
        with open(os.path.join(old, "config.json"), "w") as f:
            json.dump({"groq_api_keys": ["gsk_antiga"]}, f)
        with open(os.path.join(old, "memoria_traducoes.json"), "w") as f:
            json.dump({"HELLO": "Olá"}, f)
        with open(os.path.join(old, "aprendizado.txt"), "w") as f:
            f.write("regra antiga")
        return home, old

    def test_first_run_copies_old_install_and_never_overwrites(self):
        home, old = self._fake_install()
        data = os.path.join(self.tmp, "AppData", "MangaStudio")
        exe = os.path.join(self.tmp, "Downloads", "MangaStudio", "MangaStudio.exe")
        with mock.patch.object(app_paths, "DATA_DIR", data), \
                mock.patch.object(app_paths, "MODELS_DIR", os.path.join(data, "models")), \
                mock.patch.object(app_paths, "LOG_DIR", os.path.join(data, "logs")):
            copied = app_paths.prepare(exe_path=exe, home=home)
            self.assertEqual(sorted(os.path.basename(c) for c in copied),
                             ["aprendizado.txt", "config.json", "memoria_traducoes.json"])
            with open(os.path.join(data, "config.json")) as f:
                self.assertEqual(json.load(f)["groq_api_keys"], ["gsk_antiga"])
            with open(os.path.join(data, "aprendizado.txt")) as f:
                self.assertEqual(f.read(), "regra antiga")  # a do usuário, não a de fábrica
            self.assertTrue(os.path.isfile(os.path.join(data, "glossary.json")))  # de fábrica
            self.assertTrue(os.path.isfile(os.path.join(data, "models", "korean", "korean_v5_dict.txt")))

            with open(os.path.join(data, "config.json"), "w") as f:
                json.dump({"groq_api_keys": ["gsk_nova"]}, f)
            self.assertEqual(app_paths.prepare(exe_path=exe, home=home), [])  # 2ª execução não copia
            with open(os.path.join(data, "config.json")) as f:
                self.assertEqual(json.load(f)["groq_api_keys"], ["gsk_nova"])

    def test_legacy_dirs_requires_project_files(self):
        home, old = self._fake_install()
        os.makedirs(os.path.join(home, "Documents", "SKILL-TRADUCAO-MANGA"))  # pasta vazia: ignorada
        found = app_paths.legacy_dirs(exe_path=os.path.join(self.tmp, "x", "MangaStudio.exe"), home=home)
        self.assertEqual(found, [old])


class TestShutdownRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "studio"))
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.client = self.server.app.test_client()
        self.server.job_state["status"] = "idle"

    def test_refuses_remote_and_running_job(self):
        r = self.client.post("/api/shutdown", json={}, headers={"Cf-Ray": "abc"})
        self.assertEqual(r.status_code, 403)
        self.server.job_state["status"] = "running"
        r = self.client.post("/api/shutdown", json={})
        self.assertEqual((r.status_code, r.get_json()["running"]), (409, True))
        self.server.job_state["status"] = "idle"

    def test_local_shutdown_exits_after_reply(self):
        with mock.patch.object(self.server.threading, "Timer") as timer:
            r = self.client.post("/api/shutdown", json={})
        self.assertEqual(r.get_json(), {"success": True})
        timer.assert_called_once()
        timer.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
