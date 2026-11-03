"""Garde-fou : le scrutateur doit rester executable avec Python 3.6.8 (RHEL 8 : python3 = 3.6).

Ces controles tournent sous toutes les versions de Python. Les tests complets ont ete passes avec un vrai
Python 3.6.8 ; ici on empeche de reintroduire ce que la 3.6 ne comprend pas.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
FICHIERS = sorted(list((RACINE / "scrutateur").glob("*.py")) + list((RACINE / "tests").glob("*.py")))
# (motif, explication) : ce qui provoque une erreur a l'import ou a l'execution sous Python 3.6
INTERDITS = [
    (r"^from __future__ import annotations", "absent de la 3.6 (SyntaxError) : annotations evaluees, utiliser typing"),
    (r"(?<![\w\.])(list|dict|tuple|set|frozenset)\[", "list[...] est evalue a l'execution : utiliser typing.List, Dict, Tuple..."),
    (r"\w\]? \| None\b", "X | None : utiliser typing.Optional[X]"),
    (r"\bProtocol\b", "typing.Protocol n'existe qu'a partir de la 3.8"),
    (r"cancel_futures", "argument de shutdown() apparu en 3.9"),
    (r"assertNoLogs", "unittest : 3.10"),
    (r"\bfromisoformat\b|\bcapture_output\b|\bnullcontext\b|\bcached_property\b|\bremoveprefix\b|\bremovesuffix\b",
     "apparu apres la 3.6"),
]


class TestCompatibilitePython36(unittest.TestCase):
    def test_syntaxe_python_3_6(self):
        if sys.version_info < (3, 8):
            self.skipTest("ast.parse(feature_version=...) : Python 3.8 ou plus ; sous 3.6 l'import des modules le prouve deja")
        for fichier in FICHIERS:
            with self.subTest(fichier=fichier.name):
                ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier), feature_version=(3, 6))

    def test_constructions_absentes_de_python_3_6(self):
        for fichier in FICHIERS:
            if fichier.name == Path(__file__).name:
                continue
            code = [ligne.split("#")[0] for ligne in fichier.read_text(encoding="utf-8").splitlines()]
            for motif, raison in INTERDITS:
                with self.subTest(fichier=fichier.name, motif=motif):
                    trouves = [i + 1 for i, ligne in enumerate(code) if re.search(motif, ligne)]
                    self.assertEqual(trouves, [], "%s lignes %s : %s" % (fichier.name, trouves, raison))


if __name__ == "__main__":
    unittest.main()
