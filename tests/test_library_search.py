"""
test_library_search.py - A busca da Biblioteca usa a busca inteligente (acentos, pontuação e ordem das
palavras ignorados) nas obras traduzidas, nas originais e na janela do Google Drive.
O comportamento foi testado no navegador (Chromium); aqui fica a proteção contra regressão.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import os
import re
import unittest

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "studio", "templates", "index.html")


class TestLibrarySearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(TEMPLATE, encoding="utf-8") as f:
            cls.html = f.read()

    def test_search_input_and_clear_button(self):
        self.assertRegex(self.html, r'<input type="search" id="library-search"[^>]*oninput="filterLibrary\(\)"')
        self.assertIn('id="library-search-clear"', self.html)
        self.assertIn('id="library-search-info"', self.html)
        self.assertIn("function clearLibrarySearch()", self.html)

    def test_smart_matching_used_everywhere(self):
        self.assertIn("function normalizeMangaSearch(text)", self.html)
        self.assertIn("function mangaMatchesSearch(name, query)", self.html)
        self.assertIn(".normalize('NFD')", self.html)
        self.assertEqual(self.html.count("mangaMatchesSearch(m.name, q)"), 2)  # traduzidas e originais
        self.assertIn("cachedDriveFolders.filter(f => mangaMatchesSearch(f.name, q))", self.html)
        self.assertIsNone(re.search(r"\.name\.toLowerCase\(\)\.includes\(q\)", self.html))

    def test_empty_results_message_and_sticky_header(self):
        self.assertIn("Nenhuma obra traduzida encontrada para", self.html)
        self.assertIn("Nenhuma obra original encontrada para", self.html)
        header_css = re.search(r"\.library-header \{[^}]*\}", self.html).group(0)
        self.assertIn("position: sticky", header_css)


if __name__ == "__main__":
    unittest.main()
