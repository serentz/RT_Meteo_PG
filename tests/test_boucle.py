import threading
import time
import unittest
from collections import Counter

from scrutateur.boucle import Scrutateur
from scrutateur.config import Reglages
from tests.fakes import FauxDepot, instance, lecture_vide


def reglages(intervalle=60.0, parallele=16, etalement=0.0, partition=(0, 1)):
    return Reglages(stockage_dsn="postgresql://x", intervalle_s=intervalle, max_parallele=parallele,
                    etalement_s=etalement, partition_index=partition[0], partition_total=partition[1])


class TestBoucle(unittest.TestCase):
    def test_les_instances_sont_relevees_en_parallele(self):
        depot = FauxDepot([instance(i) for i in range(1, 6)])

        def source(_):
            time.sleep(0.4)
            return lecture_vide()

        debut = time.monotonic()
        Scrutateur(reglages(), depot, source).executer(threading.Event(), une_fois=True)
        duree = time.monotonic() - debut
        self.assertEqual(len(depot.ecrites), 5)
        self.assertLess(duree, 1.2, f"5 x 0.4 s en sequence feraient 2 s ; mesure : {duree:.2f} s")

    def test_une_instance_en_panne_n_empeche_pas_les_autres(self):
        depot = FauxDepot([instance(1), instance(2), instance(3)])

        def source(inst):
            if inst.instance_id == 2:
                raise ConnectionError("pg03 injoignable")
            return lecture_vide()

        Scrutateur(reglages(), depot, source).executer(threading.Event(), une_fois=True)
        statuts = {m.instance_id: m.statut for m in depot.ecrites}
        self.assertEqual(statuts, {1: "ok", 2: "erreur", 3: "ok"})

    def test_instance_bloquee_n_est_pas_relancee_et_les_autres_continuent(self):
        depot = FauxDepot([instance(1), instance(2)])
        debloque = threading.Event()
        appels = Counter()
        verrou = threading.Lock()

        def source(inst):
            with verrou:
                appels[inst.instance_id] += 1
            if inst.instance_id == 1:
                debloque.wait(5)  # releve qui ne rend pas la main (reseau coupe)
            return lecture_vide()

        arret = threading.Event()
        s = Scrutateur(reglages(intervalle=0.2), depot, source)
        fil = threading.Thread(target=s.executer, args=(arret,))
        fil.start()
        time.sleep(0.9)  # ~4 cycles
        debloque.set()
        arret.set()
        fil.join(5)
        self.assertFalse(fil.is_alive())
        self.assertEqual(appels[1], 1, "l'instance bloquee ne doit pas accumuler de releves")
        self.assertGreaterEqual(appels[2], 3, "l'autre instance doit etre relevee a chaque cycle")

    def test_liste_des_instances_relue_a_chaque_cycle(self):
        depot = FauxDepot([instance(1)])
        arret = threading.Event()
        s = Scrutateur(reglages(intervalle=0.2), depot, lambda i: lecture_vide())
        fil = threading.Thread(target=s.executer, args=(arret,))
        fil.start()
        time.sleep(0.3)
        depot.instances.append(instance(2))       # ajout a chaud dans meteo.instance
        time.sleep(0.6)
        depot.instances[:] = [instance(2)]         # instance 1 desactivee
        time.sleep(0.5)
        arret.set()
        fil.join(5)
        n1, n2 = len(depot.pour(1)), len(depot.pour(2))
        self.assertGreaterEqual(n2, 2, "l'instance ajoutee doit etre prise en compte sans redemarrage")
        self.assertGreaterEqual(n1, 1)
        derniere_1 = max(i for i, m in enumerate(depot.ecrites) if m.instance_id == 1)
        self.assertLess(derniere_1, len(depot.ecrites) - 1, "l'instance desactivee ne doit plus etre relevee")

    def test_postgresql_indisponible_en_lecture_ne_tue_pas_la_boucle(self):
        depot = FauxDepot([instance(1)])
        depot.panne_lecture = True
        arret = threading.Event()
        s = Scrutateur(reglages(intervalle=0.2), depot, lambda i: lecture_vide())
        fil = threading.Thread(target=s.executer, args=(arret,))
        fil.start()
        time.sleep(0.5)
        self.assertTrue(fil.is_alive(), "la boucle doit survivre a une panne de PostgreSQL")
        depot.panne_lecture = False                # retour a la normale
        time.sleep(0.5)
        arret.set()
        fil.join(5)
        self.assertGreaterEqual(len(depot.ecrites), 1, "les releves reprennent apres la panne")

    def test_arret_immediat_meme_avec_un_intervalle_de_60_s(self):
        depot = FauxDepot([instance(1)])
        arret = threading.Event()
        s = Scrutateur(reglages(intervalle=60), depot, lambda i: lecture_vide())
        fil = threading.Thread(target=s.executer, args=(arret,))
        fil.start()
        time.sleep(0.3)
        debut = time.monotonic()
        arret.set()
        fil.join(5)
        self.assertFalse(fil.is_alive())
        self.assertLess(time.monotonic() - debut, 2)

    def test_cadence_regulee_sans_derive_sur_horloge_simulee(self):
        # Chaque cycle dure 0,05 s : le cycle suivant doit partir a +0,2 s du precedent, pas a +0,25 s
        depot = FauxDepot([instance(1)])
        departs = []

        def source(_):
            departs.append(time.monotonic())
            time.sleep(0.05)
            return lecture_vide()

        arret = threading.Event()
        s = Scrutateur(reglages(intervalle=0.2), depot, source)
        fil = threading.Thread(target=s.executer, args=(arret,))
        fil.start()
        time.sleep(1.1)
        arret.set()
        fil.join(5)
        ecarts = [b - a for a, b in zip(departs, departs[1:])]
        self.assertGreaterEqual(len(ecarts), 4)
        self.assertAlmostEqual(sum(ecarts) / len(ecarts), 0.2, delta=0.04)


class TestPassageALEchelle(unittest.TestCase):
    def test_les_partitions_se_partagent_les_instances_sans_oubli_ni_doublon(self):
        instances = [instance(i) for i in range(1, 201)]
        for total in (1, 2, 3, 7):
            with self.subTest(total=total):
                parts = [[i.instance_id for i in Scrutateur(reglages(partition=(k, total)), FauxDepot(), None)
                          .instances_de_la_partition(instances)] for k in range(total)]
                tous = sorted(x for p in parts for x in p)
                self.assertEqual(tous, list(range(1, 201)))           # aucune oubliee, aucune en double
                self.assertLessEqual(max(map(len, parts)) - min(map(len, parts)), 1)  # charge equilibree

    def test_un_scrutateur_ne_releve_que_sa_partition(self):
        depot = FauxDepot([instance(i) for i in range(1, 7)])
        Scrutateur(reglages(partition=(1, 3)), depot, lambda i: lecture_vide()).executer(threading.Event(), une_fois=True)
        self.assertEqual(sorted(m.instance_id for m in depot.ecrites), [1, 4])

    def test_les_releves_sont_etales_regulierement_sur_la_fenetre(self):
        depot = FauxDepot([instance(i) for i in range(1, 6)])
        departs = {}

        def source(inst):
            departs[inst.instance_id] = time.monotonic()
            return lecture_vide()

        arret = threading.Event()
        s = Scrutateur(reglages(intervalle=10, etalement=1.0), depot, source)
        fil = threading.Thread(target=s.executer, args=(arret,))
        debut = time.monotonic()
        fil.start()
        time.sleep(1.3)
        arret.set()
        fil.join(5)
        decalages = [departs[i] - debut for i in range(1, 6)]
        for k, d in enumerate(decalages):  # 0, 0.2, 0.4, 0.6, 0.8 s
            self.assertAlmostEqual(d, k * 0.2, delta=0.12)

    def test_une_fois_ne_fait_pas_d_etalement(self):
        depot = FauxDepot([instance(i) for i in range(1, 6)])
        debut = time.monotonic()
        Scrutateur(reglages(intervalle=10, etalement=5.0), depot, lambda i: lecture_vide()).executer(threading.Event(), une_fois=True)
        self.assertLess(time.monotonic() - debut, 1.0)
        self.assertEqual(len(depot.ecrites), 5)

    def test_arret_pendant_l_etalement_est_immediat(self):
        depot = FauxDepot([instance(i) for i in range(1, 6)])
        arret = threading.Event()
        s = Scrutateur(reglages(intervalle=60, etalement=30.0), depot, lambda i: lecture_vide())
        fil = threading.Thread(target=s.executer, args=(arret,))
        fil.start()
        time.sleep(0.3)
        debut = time.monotonic()
        arret.set()
        fil.join(5)
        self.assertFalse(fil.is_alive())
        self.assertLess(time.monotonic() - debut, 2)

    def test_avertissement_quand_il_y_a_plus_de_releves_en_cours_que_de_threads(self):
        depot = FauxDepot([instance(i) for i in range(1, 6)])
        debloque = threading.Event()

        def source(_):
            debloque.wait(5)
            return lecture_vide()

        s = Scrutateur(reglages(parallele=2), depot, source)
        s._pool = __import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=2)
        try:
            with self.assertLogs("scrutateur.boucle", level="WARNING") as logs:
                s.lancer_cycle()
            self.assertIn("SCRUTATEUR_PARTITION", "\n".join(logs.output))
        finally:
            debloque.set()
            s._pool.shutdown(wait=True)

    def test_pas_d_avertissement_quand_les_threads_suffisent(self):
        depot = FauxDepot([instance(i) for i in range(1, 4)])
        s = Scrutateur(reglages(parallele=16), depot, lambda i: lecture_vide())
        with self.assertNoLogs("scrutateur.boucle", level="WARNING"):
            s.executer(threading.Event(), une_fois=True)


if __name__ == "__main__":
    unittest.main()
