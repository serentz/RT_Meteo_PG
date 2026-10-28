import unittest

from scrutateur.collecte import collecter_et_enregistrer, message_erreur
from scrutateur.modeles import Lecture, LigneProcessus
from tests.fakes import FauxDepot, instance, lecture_vide


class TestCollecte(unittest.TestCase):
    def test_releve_reussi_est_enregistre_en_ok(self):
        depot = FauxDepot()
        lecture = Lecture([LigneProcessus(11, "lock sleep", "UPDATE", "app", 10, 45, 120)])
        m = collecter_et_enregistrer(instance(1), lambda i: lecture, depot)
        self.assertEqual(m.statut, "ok")
        self.assertEqual(depot.ecrites, [m])
        self.assertEqual(m.indicateurs.blocage_max_s, 45.0)
        self.assertEqual(m.indicateurs.requete_max_s, 120.0)

    def test_panne_cible_devient_une_mesure_erreur_sans_exception(self):
        depot = FauxDepot()

        def source(_):
            raise TimeoutError("Login timeout expired")

        m = collecter_et_enregistrer(instance(1), source, depot)
        self.assertEqual(m.statut, "erreur")
        self.assertIn("Login timeout expired", m.erreur)
        self.assertIsNone(m.indicateurs)
        self.assertEqual(depot.ecrites, [m])

    def test_le_mot_de_passe_n_est_jamais_dans_l_erreur_ni_dans_le_repr(self):
        inst = instance(1, password="Tr0ub4dor&3")

        def source(_):
            raise RuntimeError("Echec de connexion : PWD=Tr0ub4dor&3 refuse")

        m = collecter_et_enregistrer(inst, source, FauxDepot())
        self.assertNotIn("Tr0ub4dor&3", m.erreur)
        self.assertIn("***", m.erreur)
        self.assertNotIn("Tr0ub4dor&3", repr(inst))

    def test_message_erreur_une_ligne_et_tronque(self):
        msg = message_erreur(RuntimeError("a\nb\n" + "x" * 2000), instance(1))
        self.assertNotIn("\n", msg)
        self.assertLessEqual(len(msg), 500)

    def test_postgresql_indisponible_ne_propage_pas_l_exception(self):
        depot = FauxDepot()
        depot.panne_ecriture = True
        m = collecter_et_enregistrer(instance(1), lambda i: lecture_vide(), depot)
        self.assertEqual(m.statut, "ok")
        self.assertEqual(depot.ecrites, [])

    def test_duree_mesuree_avec_l_horloge(self):
        temps = iter([100.0, 100.25])
        m = collecter_et_enregistrer(instance(1), lambda i: lecture_vide(), FauxDepot(), horloge=lambda: next(temps))
        self.assertEqual(m.duree_ms, 250)


if __name__ == "__main__":
    unittest.main()
