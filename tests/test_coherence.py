import json
import pathlib
import re
import unittest

from scrutateur.cible import SQL_PROCESSUS

RACINE = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = RACINE / "sql" / "stockage" / "001_schema.sql"


def normalise(texte: str) -> str:
    return re.sub(r"\s+", " ", texte).strip()


def sans_commentaires(texte: str) -> str:
    return "\n".join(l for l in texte.splitlines() if not l.lstrip().startswith("--"))


class TestCoherence(unittest.TestCase):
    def test_requete_identique_au_fichier_sql(self):
        fichier = normalise((RACINE / "sql" / "cible" / "supervision.sql").read_text(encoding="utf-8"))
        self.assertIn(normalise(SQL_PROCESSUS), fichier)

    def test_une_seule_requete_sur_la_cible(self):
        fichier = sans_commentaires((RACINE / "sql" / "cible" / "supervision.sql").read_text(encoding="utf-8"))
        self.assertEqual(fichier.count(";"), 1)

    def test_la_requete_est_en_lecture_seule(self):
        self.assertTrue(SQL_PROCESSUS.lstrip().upper().startswith("WITH"))
        self.assertNotRegex(SQL_PROCESSUS.upper(), r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|COPY)\b")

    def test_aucune_extension_ni_compteur_cumulatif(self):
        bas = SQL_PROCESSUS.lower()
        self.assertNotIn("pg_stat_statements", bas)
        self.assertNotIn("pg_stat_reset", bas)
        self.assertNotIn("pg_stat_database", bas)

    def test_le_texte_des_requetes_n_est_jamais_conserve(self):
        # seul le premier mot de s.query est lu ; la colonne brute n'est pas dans la liste du SELECT
        self.assertIn("split_part(ltrim(s.query)", SQL_PROCESSUS)
        self.assertNotRegex(SQL_PROCESSUS, r"s\.query\s+AS")

    def test_la_requete_exclut_la_session_du_scrutateur_et_les_processus_internes(self):
        self.assertIn("pg_backend_pid()", SQL_PROCESSUS)
        self.assertIn("backend_type = 'client backend'", SQL_PROCESSUS)

    def test_les_sessions_inactives_sont_ecartees_sauf_transaction_ou_blocage(self):
        self.assertIn("s.state = 'active'", SQL_PROCESSUS)
        self.assertIn("s.xact_start IS NOT NULL", SQL_PROCESSUS)
        self.assertIn("pg_blocking_pids", SQL_PROCESSUS)

    def test_ligne_processus_attend_les_colonnes_de_la_requete(self):
        from scrutateur import cible
        self.assertEqual(len(cible.ligne_processus((1,) + (None,) * 12).__dict__), 13)

    def test_la_fonction_sql_a_le_meme_nombre_de_parametres_que_le_depot(self):
        from scrutateur.store import SQL_ENREGISTRER

        bloc = SCHEMA.read_text(encoding="utf-8").split("CREATE OR REPLACE FUNCTION meteo.enregistrer_mesure(")[1].split(") RETURNS")[0]
        self.assertEqual(len(re.findall(r"^\s*p_\w+", bloc, flags=re.M)), SQL_ENREGISTRER.count("%s"))

    def test_les_cles_json_du_depot_sont_lues_par_la_fonction_sql(self):
        from scrutateur.indicateurs import calculer_indicateurs
        from scrutateur.modeles import Lecture, LigneProcessus, Mesure
        from scrutateur.store import parametres_enregistrement

        mesure = Mesure(1, "ok", 1, indicateurs=calculer_indicateurs(Lecture([LigneProcessus(1, "active", "c", "l", 0, execution_s=1)])))
        cles = json.loads(parametres_enregistrement(mesure)[10])[0].keys()
        corps = SCHEMA.read_text(encoding="utf-8").split("CREATE OR REPLACE FUNCTION meteo.enregistrer_mesure(")[1].split("$$;")[0]
        for cle in cles:
            self.assertIn(f"e->>'{cle}'", corps, f"la cle JSON {cle!r} n'est pas lue par la fonction SQL")


if __name__ == "__main__":
    unittest.main()
