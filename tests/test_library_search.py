"""
test_library_search.py - A busca da Biblioteca usa a busca inteligente (acentos, pontuação e ordem das
palavras ignorados) nas obras traduzidas, nas originais e na janela do Google Drive.
Desde a v0.8.0 a interface fica em templates/partials, static/js e static/css; o teste lê todos.
Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
"""

import glob
import os
import re
import unittest

STUDIO = os.path.join(os.path.dirname(__file__), "..", "studio")


def _read_all(*patterns):
    text = []
    for pat in patterns:
        for path in sorted(glob.glob(os.path.join(STUDIO, pat))):
            with open(path, encoding="utf-8") as f:
                text.append(f.read())
    return "\n".join(text)


class TestLibrarySearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _read_all("templates/*.html", "templates/partials/*.html")
        cls.js = _read_all("static/js/*.js")
        cls.css = _read_all("static/css/*.css")

    def test_search_input_and_clear_button(self):
        self.assertRegex(self.html, r'<input type="search" id="library-search"[^>]*oninput="filterLibrary\(\)"')
        self.assertIn('id="library-search-clear"', self.html)
        self.assertIn('id="library-search-info"', self.html)
        self.assertIn("function clearLibrarySearch()", self.js)

    def test_smart_matching_used_everywhere(self):
        self.assertIn("function normalizeMangaSearch(text)", self.js)
        self.assertIn("function mangaMatchesSearch(name, query)", self.js)
        self.assertIn(".normalize('NFD')", self.js)
        self.assertEqual(self.js.count("mangaMatchesSearch(m.name, q)"), 2)  # traduzidas e originais
        self.assertIn("cachedDriveFolders.filter(f => mangaMatchesSearch(f.name, q))", self.js)
        self.assertIsNone(re.search(r"\.name\.toLowerCase\(\)\.includes\(q\)", self.js))

    def test_empty_results_message_and_sticky_header(self):
        self.assertIn("Nenhuma obra traduzida encontrada para", self.js)
        self.assertIn("Nenhuma obra original encontrada para", self.js)
        header_css = re.search(r"\.library-header \{[^}]*\}", self.css).group(0)
        self.assertIn("position: sticky", header_css)


class TestFrontendStructure(unittest.TestCase):
    """v0.8.0: interface dividida em arquivos pequenos; nada que o JavaScript usa pode sumir do HTML."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read_all("templates/*.html", "templates/partials/*.html")
        cls.js = _read_all("static/js/*.js")

    def test_every_id_used_by_js_exists_in_html(self):
        used = set(re.findall(r"getElementById\('([\w-]+)'\)", self.js))
        defined = set(re.findall(r'id="([\w-]+)"', self.html))
        legacy = {"selected-cover-img", "selected-cover-placeholder", "selected-manga-name"}  # opcionais no JS
        self.assertEqual(sorted(used - defined - legacy), [])

    def test_all_scripts_are_included_and_small(self):
        for path in glob.glob(os.path.join(STUDIO, "static", "js", "*.js")) + \
                glob.glob(os.path.join(STUDIO, "static", "css", "*.css")) + \
                glob.glob(os.path.join(STUDIO, "templates", "partials", "*.html")):
            with open(path, encoding="utf-8") as f:
                self.assertLess(len(f.read().splitlines()), 300, path)
            if path.endswith(".js"):
                name = os.path.splitext(os.path.basename(path))[0]
                self.assertIn(f"'{name}'", self.html, f"{name}.js não está no index.html")

    def test_theme_toggle_and_no_external_fonts(self):
        self.assertIn("function toggleTheme()", self.js)
        self.assertIn('onclick="toggleTheme()"', self.html)
        self.assertNotIn("fonts.googleapis.com", self.html)  # o .exe precisa funcionar sem internet


if __name__ == "__main__":
    unittest.main()
