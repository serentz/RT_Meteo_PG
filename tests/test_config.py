import unittest

from scrutateur.config import ErreurConfiguration, Reglages


class TestConfig(unittest.TestCase):
    def test_defauts(self):
        r = Reglages.depuis_env({"SCRUTATEUR_STOCKAGE_DSN": "postgresql://u:p@pg01/meteo"})
        self.assertEqual((r.intervalle_s, r.max_parallele, r.cible_sslmode), (60.0, 16, "prefer"))

    def test_dsn_obligatoire(self):
        with self.assertRaises(ErreurConfiguration):
            Reglages.depuis_env({})

    def test_valeurs_invalides(self):
        base = {"SCRUTATEUR_STOCKAGE_DSN": "x"}
        for cle, val in [("SCRUTATEUR_INTERVALLE_S", "abc"), ("SCRUTATEUR_INTERVALLE_S", "1"),
                         ("SCRUTATEUR_MAX_PARALLELE", "0"), ("SCRUTATEUR_CIBLE_CONNEXION_TIMEOUT_S", "0"),
                         ("SCRUTATEUR_CIBLE_SSLMODE", "n_importe_quoi")]:
            with self.subTest(cle=cle, val=val), self.assertRaises(ErreurConfiguration):
                Reglages.depuis_env({**base, cle: val})

    def test_le_dsn_n_apparait_pas_dans_repr(self):
        self.assertNotIn("secret", repr(Reglages.depuis_env({"SCRUTATEUR_STOCKAGE_DSN": "postgresql://u:secret@pg01/meteo"})))

    def test_partition_et_etalement(self):
        base = {"SCRUTATEUR_STOCKAGE_DSN": "x"}
        r = Reglages.depuis_env(base)
        self.assertEqual((r.partition_index, r.partition_total, r.etalement_s), (0, 1, 20.0))
        r = Reglages.depuis_env({**base, "SCRUTATEUR_PARTITION": "2/4", "SCRUTATEUR_ETALEMENT_S": "0"})
        self.assertEqual((r.partition_index, r.partition_total, r.etalement_s), (2, 4, 0.0))

    def test_partition_ou_etalement_invalides(self):
        base = {"SCRUTATEUR_STOCKAGE_DSN": "x"}
        for cle, val in [("SCRUTATEUR_PARTITION", "4/4"), ("SCRUTATEUR_PARTITION", "-1/2"), ("SCRUTATEUR_PARTITION", "0/0"),
                         ("SCRUTATEUR_PARTITION", "deux"), ("SCRUTATEUR_ETALEMENT_S", "31"), ("SCRUTATEUR_ETALEMENT_S", "-1")]:
            with self.subTest(cle=cle, val=val), self.assertRaises(ErreurConfiguration):
                Reglages.depuis_env({**base, cle: val})

    def test_pire_duree_de_releve(self):
        self.assertEqual(Reglages(stockage_dsn="x").pire_duree_releve_s, 40)  # connexion 10 s + deux requetes de 15 s


if __name__ == "__main__":
    unittest.main()
