"""
test_ficha_obra.py - Ficha da Obra: onde fica, ler/salvar, mesclar sem sobrescrever e bloco do prompt.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import ficha_obra as fo


class TestResolvePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.obra = os.path.join(self.tmp, "MANGAS", "Minha Obra")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _mk(self, *parts):
        p = os.path.join(*parts)
        os.makedirs(p, exist_ok=True)
        return p

    def test_chapter_folder_uses_work_folder(self):
        for name in ("Cap 12", "Capítulo 3", "Chapter 7", "ch.15", "015", "第12話", "Minha Obra - Ep 4"):
            cap = self._mk(self.obra, name)
            self.assertEqual(fo.resolve_ficha_path(cap), os.path.join(self.obra, fo.FICHA_FILENAME), name)

    def test_single_folder_work_uses_itself(self):
        self._mk(self.obra)
        self.assertEqual(fo.resolve_ficha_path(self.obra), os.path.join(self.obra, fo.FICHA_FILENAME))

    def test_chapter_directly_under_mangas_root_stays_local(self):
        cap = self._mk(self.tmp, "MANGAS", "015")
        self.assertEqual(fo.resolve_ficha_path(cap), os.path.join(cap, fo.FICHA_FILENAME))

    def test_existing_files_win(self):
        cap = self._mk(self.obra, "Chainsaw")  # não parece capítulo
        parent_f = os.path.join(self.obra, fo.FICHA_FILENAME)
        with open(parent_f, "w", encoding="utf-8") as f:
            f.write("{}")
        self.assertEqual(fo.resolve_ficha_path(cap), parent_f)
        local_f = os.path.join(cap, fo.FICHA_FILENAME)
        with open(local_f, "w", encoding="utf-8") as f:
            f.write("{}")
        self.assertEqual(fo.resolve_ficha_path(cap), local_f)

    def test_non_chapter_names(self):
        for name in ("Chainsaw Man", "Capa", "Episodios extras", "One Piece"):
            self.assertFalse(fo.looks_like_chapter(name), name)


class TestLoadSave(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, fo.FICHA_FILENAME)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_file_gives_empty(self):
        ficha = fo.load_ficha(self.path, obra="X")
        self.assertEqual(ficha["obra"], "X")
        self.assertEqual(ficha["personagens"], [])

    def test_roundtrip_and_sanitizes(self):
        data = {"obra": "X", "personagens": [{"original": "林娜", "pt": "Lin Na", "genero": "feminino"},
                                              {"original": ""}, "lixo"],
                "termos": [{"original": "灵石", "pt": "pedra espiritual"}, {"original": "a"}]}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        ficha = fo.load_ficha(self.path)
        self.assertEqual(len(ficha["personagens"]), 1)
        self.assertEqual(ficha["personagens"][0]["genero"], "F")
        self.assertEqual(len(ficha["termos"]), 1)
        self.assertTrue(fo.save_ficha(ficha, self.path))
        again = fo.load_ficha(self.path)
        self.assertEqual(again["personagens"][0]["pt"], "Lin Na")
        self.assertTrue(again["atualizado_em"])
        self.assertEqual([f for f in os.listdir(self.tmp) if f.endswith(".tmp")], [])

    def test_corrupt_file_is_backed_up(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{quebrado")
        ficha = fo.load_ficha(self.path, obra="X")
        self.assertEqual(ficha["personagens"], [])
        self.assertTrue(os.path.exists(self.path + ".corrompido.bak"))


class TestMerge(unittest.TestCase):
    def _ficha(self):
        f = fo.empty_ficha("X")
        f["personagens"].append({"original": "林娜", "pt": "Lin Na", "genero": "F", "nota": ""})
        f["personagens"].append({"original": "阿杰", "pt": "A Jie", "genero": "?", "nota": ""})
        f["termos"].append({"original": "灵石", "pt": "pedra espiritual", "nota": ""})
        return f

    def test_adds_new_and_never_overwrites(self):
        f = self._ficha()
        rep = fo.merge_novidades(f, {
            "personagens": [{"original": "王浩", "pt": "Wang Hao", "genero": "M"},
                            {"original": "林娜", "pt": "Lina", "genero": "M", "nota": "irmã"}],
            "termos": [{"original": "宗门", "pt": "seita"}, {"original": "灵石", "pt": "cristal"}],
        }, capitulo="Cap 2")
        self.assertEqual(rep["personagens_novos"], ["王浩"])
        self.assertEqual(rep["termos_novos"], ["宗门"])
        lin = f["personagens"][0]
        self.assertEqual((lin["pt"], lin["genero"]), ("Lin Na", "F"))
        self.assertEqual(lin["nota"], "irmã")  # nota vazia pode ser completada
        self.assertEqual(f["termos"][0]["pt"], "pedra espiritual")
        self.assertEqual(len(rep["conflitos"]), 3)
        self.assertTrue(all(c.startswith("[Cap 2]") for c in f["conflitos"]))

    def test_completes_unknown_gender(self):
        f = self._ficha()
        rep = fo.merge_novidades(f, {"personagens": [{"original": "阿杰", "pt": "A Jie", "genero": "M"}]})
        self.assertEqual(rep["generos_completados"], ["阿杰"])
        self.assertEqual(f["personagens"][1]["genero"], "M")
        self.assertEqual(rep["conflitos"], [])

    def test_conflicts_are_not_repeated(self):
        f = self._ficha()
        nov = {"personagens": [{"original": "林娜", "pt": "Lin Na", "genero": "M"}]}
        fo.merge_novidades(f, nov, capitulo="Cap 2")
        fo.merge_novidades(f, nov, capitulo="Cap 3")
        self.assertEqual(len(f["conflitos"]), 1)

    def test_punctuation_variants_are_same_entry(self):
        f = self._ficha()
        rep = fo.merge_novidades(f, {"personagens": [{"original": "林娜！", "pt": "Lin Na", "genero": "F"}]})
        self.assertEqual(rep["personagens_novos"], [])
        self.assertEqual(len(f["personagens"]), 2)

    def test_term_equal_to_character_is_skipped(self):
        f = self._ficha()
        rep = fo.merge_novidades(f, {"termos": [{"original": "林娜", "pt": "Lin Na"}]})
        self.assertEqual(rep["termos_novos"], [])

    def test_limits_and_bad_input(self):
        f = fo.empty_ficha()
        many = [{"original": f"Nome{i}", "pt": f"Nome{i}", "genero": "?"} for i in range(fo.MAX_PERSONAGENS + 20)]
        fo.merge_novidades(f, {"personagens": many})
        self.assertEqual(len(f["personagens"]), fo.MAX_PERSONAGENS)
        self.assertEqual(fo.merge_novidades(f, None)["personagens_novos"], [])
        self.assertEqual(fo.merge_novidades(f, {"personagens": "x", "termos": [1, None]})["termos_novos"], [])

    def test_chapter_tracking(self):
        f = fo.empty_ficha()
        self.assertFalse(fo.chapter_already_read(f, "Cap 1"))
        fo.mark_chapter_read(f, "Cap 1")
        fo.mark_chapter_read(f, "Cap 1")
        self.assertEqual(f["capitulos_lidos"], ["Cap 1"])
        self.assertTrue(fo.chapter_already_read(f, "Cap 1"))


class TestPromptBlock(unittest.TestCase):
    def _ficha(self):
        f = fo.empty_ficha("X")
        for i in range(40):
            f["personagens"].append({"original": f"Extra{i}", "pt": f"Extra{i}", "genero": "?", "nota": ""})
        f["personagens"].append({"original": "Yu-kun", "pt": "Yu-kun", "genero": "M", "nota": "filho"})
        f["termos"].append({"original": "灵石", "pt": "pedra espiritual", "nota": ""})
        return f

    def test_relevant_entries_come_first(self):
        block = fo.build_prompt_block(self._ficha(), ["Welcome home, Yu-kun!", "给我灵石"], max_chars=300)
        self.assertIn("FICHA DA OBRA", block)
        lines = [l for l in block.splitlines() if l.startswith("- ")]
        self.assertEqual(lines[0], "- Yu-kun -> Yu-kun (homem): filho")
        self.assertEqual(lines[1], "- 灵石 -> pedra espiritual")
        self.assertLessEqual(len(block), 300)

    def test_latin_names_need_whole_word(self):
        f = fo.empty_ficha()
        f["personagens"].append({"original": "Al", "pt": "Al", "genero": "M", "nota": ""})
        f["personagens"].append({"original": "Zed", "pt": "Zed", "genero": "M", "nota": ""})
        block = fo.build_prompt_block(f, ["Zed, call them all"])
        lines = [l for l in block.splitlines() if l.startswith("- ")]
        self.assertTrue(lines[0].startswith("- Zed"))

    def test_empty_cases(self):
        self.assertEqual(fo.build_prompt_block(None, ["x"]), "")
        self.assertEqual(fo.build_prompt_block(fo.empty_ficha(), ["x"]), "")
        self.assertEqual(fo.build_prompt_block({"personagens": "quebrado"}, ["x"]), "")


class TestEnabled(unittest.TestCase):
    def test_env_and_config(self):
        with mock.patch.dict(os.environ, {"MANGA_FICHA": ""}):
            self.assertTrue(fo.is_enabled(None))
            self.assertFalse(fo.is_enabled({"ficha_obra": False}))
        with mock.patch.dict(os.environ, {"MANGA_FICHA": "0"}):
            self.assertFalse(fo.is_enabled({"ficha_obra": True}))
        with mock.patch.dict(os.environ, {"MANGA_FICHA": "1"}):
            self.assertTrue(fo.is_enabled({"ficha_obra": False}))


if __name__ == "__main__":
    unittest.main()
