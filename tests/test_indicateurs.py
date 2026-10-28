import unittest

from scrutateur.indicateurs import MAX_DETAILS, calculer_indicateurs
from scrutateur.modeles import Lecture, LigneProcessus


def p(pid, bloqueur=0, blocage=None, exe=None, cmd="SELECT", statut="active", login="app", tr=None):
    """Une ligne du tableau : blocage_s, execution_s (None si inactive), transaction_s (None hors transaction)."""
    return LigneProcessus(pid, statut, cmd, login, bloqueur, blocage, exe, tr)


class TestIndicateurs(unittest.TestCase):
    def test_instance_calme_donne_zero_et_pas_none(self):
        # Processus connectes mais sans requete en cours ni blocage : tous les indicateurs valent 0
        r = calculer_indicateurs(Lecture([p(10, statut="idle"), p(11, statut="idle")]))
        self.assertEqual((r.nb_bloques, r.blocage_max_s, r.blocage_moyen_s), (0, 0.0, 0.0))
        self.assertEqual((r.nb_requetes, r.requete_max_s, r.requete_moyenne_s), (0, 0.0, 0.0))

    def test_lecture_totalement_vide(self):
        r = calculer_indicateurs(Lecture([]))
        self.assertEqual((r.nb_bloques, r.nb_requetes, r.details), (0, 0, []))

    def test_blocage_max_et_moyenne_sur_les_seuls_bloques(self):
        # 3 processus dont 2 bloques (40 s et 20 s) : la moyenne ignore le processus non bloque
        r = calculer_indicateurs(Lecture([p(10, exe=5), p(11, 10, 40, 60), p(12, 10, 20, 30)]))
        self.assertEqual(r.nb_bloques, 2)
        self.assertEqual(r.blocage_max_s, 40.0)
        self.assertEqual(r.blocage_moyen_s, 30.0)

    def test_requete_max_et_moyenne(self):
        r = calculer_indicateurs(Lecture([p(10, exe=10), p(11, exe=30), p(12, exe=80)]))
        self.assertEqual(r.nb_requetes, 3)
        self.assertEqual(r.requete_max_s, 80.0)
        self.assertEqual(r.requete_moyenne_s, 40.0)

    def test_les_processus_bloques_comptent_parmi_les_requetes_en_cours(self):
        r = calculer_indicateurs(Lecture([p(10, exe=10), p(11, 10, 40, 100)]))
        self.assertEqual((r.nb_requetes, r.requete_max_s), (2, 100.0))
        self.assertEqual(r.blocage_max_s, 40.0)

    def test_bloqueur_inactif_est_liste_mais_ne_compte_dans_aucune_moyenne(self):
        # pid 10 : en attente de commande, donc execution_time NULL ; il bloque le pid 11
        r = calculer_indicateurs(Lecture([p(10, cmd="UPDATE", statut="idle"), p(11, 10, 40, 40)]))
        self.assertEqual(sorted(d.pid for d in r.details), [10, 11])
        par_pid = {d.pid: d for d in r.details}
        self.assertEqual(par_pid[11].bloqueur_pid, 10)  # le bloqueur est identifiable
        self.assertEqual((r.nb_bloques, r.nb_requetes), (1, 1))
        self.assertEqual(r.requete_moyenne_s, 40.0)

    def test_valeurs_nulles_ou_negatives_ne_cassent_rien(self):
        r = calculer_indicateurs(Lecture([p(10, bloqueur=5, blocage=None, exe=-3), p(11, exe=None)]))
        self.assertEqual((r.nb_bloques, r.blocage_max_s), (1, 0.0))
        self.assertEqual((r.nb_requetes, r.requete_max_s), (1, 0.0))

    def test_un_pid_en_double_n_apparait_qu_une_fois(self):
        r = calculer_indicateurs(Lecture([p(10, exe=5), p(10, exe=50)]))
        self.assertEqual([d.pid for d in r.details], [10])
        self.assertEqual(r.requete_max_s, 50.0)

    def test_details_tries_par_gravite_puis_pid(self):
        r = calculer_indicateurs(Lecture([p(30, exe=1), p(10, exe=2), p(20, exe=3)]))
        self.assertEqual([d.pid for d in r.details], [20, 10, 30])  # execution la plus longue d'abord

    def test_session_inactive_n_entre_pas_dans_les_requetes(self):
        inactives = [p(1, statut="idle in transaction", tr=50), p(2, statut="idle")]
        r = calculer_indicateurs(Lecture(inactives + [p(3, exe=30), p(4, exe=10)]))
        self.assertEqual(r.nb_requetes, 2)
        self.assertEqual((r.requete_max_s, r.requete_moyenne_s), (30.0, 20.0))
        self.assertEqual(len(r.details), 4)

    def test_requete_active_de_moins_d_une_seconde_compte_comme_requete(self):
        r = calculer_indicateurs(Lecture([p(1, exe=0), p(2, exe=20)]))
        self.assertEqual((r.nb_requetes, r.requete_moyenne_s), (2, 10.0))

    def test_transaction_max_et_nombre(self):
        r = calculer_indicateurs(Lecture([p(1, statut="idle in transaction", tr=30), p(2, tr=900, exe=5), p(3, tr=120), p(4)]))
        self.assertEqual((r.nb_transactions, r.transaction_max_s), (3, 900.0))
        self.assertEqual((r.nb_bloques, r.nb_requetes), (0, 1))

    def test_aucune_transaction_donne_zero(self):
        r = calculer_indicateurs(Lecture([p(1, exe=3)]))
        self.assertEqual((r.nb_transactions, r.transaction_max_s), (0, 0.0))

    def test_details_les_plus_graves_d_abord_et_plafonnes(self):
        lignes = [p(i, exe=1) for i in range(1, 301)] + [p(999, 5, 40, 40, tr=40)]
        r = calculer_indicateurs(Lecture(lignes))
        self.assertEqual(len(r.details), MAX_DETAILS)
        self.assertEqual(r.details[0].pid, 999)

    def test_moyenne_arrondie_a_une_decimale(self):
        r = calculer_indicateurs(Lecture([p(1, 9, 1), p(2, 9, 1), p(3, 9, 2)]))
        self.assertEqual(r.blocage_moyen_s, 1.3)


if __name__ == "__main__":
    unittest.main()
