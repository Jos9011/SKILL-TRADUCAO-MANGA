"""
test_ficha_caminho.py - Ficha encontrada pelo nome da obra (pastas soltas), obra/capítulo e fichas antigas.
Também cobre as melhorias do Líder: apelidos, palpites e nomes completos.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import shutil
import tempfile
import unittest

import ficha_caminho as fc
import ficha_obra
import lider_capitulo as lc

OBRA = "Toshiue no Kuro Gal Doukyuusei - OLDER BLACK GAL CLASSMATE"


class TestObraName(unittest.TestCase):
    def test_chapter_suffixes_are_removed(self):
        cases = {
            f"{OBRA} Ch.1": OBRA,
            "GTS Great Teacher Sayoko Lesson 10": "GTS Great Teacher Sayoko",
            "Kanojo Saimin 4 _ Hypnosis Girlfriend 4": "Kanojo Saimin _ Hypnosis Girlfriend",
            "Mesugaki Rina-chan VOL. 3 (decensored)": "Mesugaki Rina-chan",
            "Mahou no Juujin Foxy Rena 23": "Mahou no Juujin Foxy Rena",
            "Minha Obra - Capítulo 12": "Minha Obra",
            "Minha Obra 第3話": "Minha Obra",
            "Kimi to Issho": "Kimi to Issho",
        }
        for folder, title in cases.items():
            self.assertEqual(fc.obra_title(folder), title, folder)

    def test_chapters_of_same_work_share_file(self):
        self.assertEqual(fc.ficha_filename(f"{OBRA} Ch.1"), fc.ficha_filename(f"{OBRA} Ch.2"))
        self.assertEqual(fc.ficha_filename("GTS Great Teacher Sayoko Lesson 3"),
                         fc.ficha_filename("GTS Great Teacher Sayoko Lesson 10"))
        self.assertNotEqual(fc.ficha_filename("Kimi to Issho"), fc.ficha_filename("Koi _ Love"))
        self.assertTrue(fc.ficha_filename('Obra: "A/B" Ch.1').endswith(".json"))
        self.assertNotIn("/", fc.ficha_filename('Obra: "A/B" Ch.1'))


class TestResolve(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = os.path.join(self.tmp, "MANGAS [PT-BR]")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mk(self, *parts):
        p = os.path.join(*parts)
        os.makedirs(p, exist_ok=True)
        return p

    def test_flat_chapters_share_one_ficha(self):
        c1 = self._mk(self.root, f"{OBRA} Ch.1")
        c2 = self._mk(self.root, f"{OBRA} Ch.2")
        p1, p2 = fc.resolve_ficha_path(c1), fc.resolve_ficha_path(c2)
        self.assertEqual(p1, p2)
        self.assertEqual(os.path.dirname(p1), os.path.join(self.root, fc.FICHAS_DIR))
        self.assertEqual(fc.obra_display_name(c1, p1), OBRA)

    def test_flat_chapter_outside_mangas_root(self):
        downloads = self._mk(self.tmp, "Downloads")
        cap = self._mk(downloads, "Obra X Ch.1")
        self.assertEqual(fc.resolve_ficha_path(cap), os.path.join(downloads, fc.FICHAS_DIR, "obra x.json"))

    def test_nested_chapters(self):
        obra = self._mk(self.tmp, "MANGAS", "Minha Obra")
        for name in ("Cap 1", "Minha Obra Cap 2", "015"):
            cap = self._mk(obra, name)
            path = fc.resolve_ficha_path(cap)
            self.assertEqual(path, os.path.join(obra, fc.FICHA_FILENAME), name)
            self.assertEqual(fc.obra_display_name(cap, path), "Minha Obra")

    def test_old_ficha_in_chapter_folder_still_wins(self):
        cap = self._mk(self.root, f"{OBRA} Ch.1")
        old = os.path.join(cap, fc.FICHA_FILENAME)
        with open(old, "w", encoding="utf-8") as fh:
            fh.write("{}")
        self.assertEqual(fc.resolve_ficha_path(cap), old)
        self.assertEqual(fc.obra_display_name(cap, old, fallback="X"), "X")

    def test_end_to_end_two_chapters(self):
        c1 = self._mk(self.root, f"{OBRA} Ch.1")
        c2 = self._mk(self.root, f"{OBRA} Ch.2")

        def fake_exec(messages, engine_opts=None, **kw):
            return ('{"personagens":[{"original":"MANABU TOKITO","pt":"MANABU TOKITO","genero":"M",'
                    '"nota":"protagonista"}],"termos":[]}')

        ctx = lc.run_for_chapter(c1, "x", ["MANABU TOKITO", "HOW LONG WAS I ASLEEP?"], {}, fake_exec,
                                 config={}, log=lambda *_: None)
        lc.save_if_changed(ctx)
        ctx2 = lc.run_for_chapter(c2, "x", ["MANABU!"], None, fake_exec, config={}, log=lambda *_: None)
        self.assertEqual(ctx2["path"], ctx["path"])
        self.assertEqual(ctx2["ficha"]["obra"], OBRA)
        self.assertEqual(ctx2["ficha"]["personagens"][0]["pt"], "Manabu Tokito")


class TestLeaderQuality(unittest.TestCase):
    def test_prompt_rules(self):
        for rule in ("APELIDOS", "NOME PRÓPRIO", "COMPLETO", "NÃO chute"):
            self.assertIn(rule, lc.SYSTEM_PROMPT)

    def test_guesses_are_dropped_and_names_capitalized(self):
        nov = {"personagens": [
            {"original": "MANABU TOKITO", "pt": "MANABU TOKITO", "genero": "M", "nota": "protagonista"},
            {"original": "SUNAHAMA-NOSAME", "pt": "Sunahama", "genero": "?", "nota": "possível nome da empresa"},
            {"original": "KIRARA", "pt": "Kirara?", "genero": "F", "nota": ""},
        ], "termos": [{"original": "T University", "pt": "Universidade T", "nota": "talvez Tóquio"}]}
        out = lc.filter_grounded(nov, ["MANABU TOKITO", "SUNAHAMA-NOSAME KIRARA", "FROM T UNIVERSITY"])
        self.assertEqual([p["pt"] for p in out["personagens"]], ["Manabu Tokito"])
        self.assertEqual(out["termos"], [])

    def test_short_and_full_name_are_same_character(self):
        ficha = ficha_obra.empty_ficha()
        ficha["personagens"].append({"original": "MANABU", "pt": "Manabu", "genero": "?", "nota": ""})
        rep = ficha_obra.merge_novidades(ficha, {"personagens": [
            {"original": "MANABU TOKITO", "pt": "Manabu Tokito", "genero": "M", "nota": "protagonista"}]})
        self.assertEqual(len(ficha["personagens"]), 1)
        self.assertEqual(ficha["personagens"][0]["genero"], "M")
        self.assertEqual(rep["personagens_novos"], [])
        self.assertEqual(rep["generos_completados"], ["MANABU"])


if __name__ == "__main__":
    unittest.main()
