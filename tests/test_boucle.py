import threading
import time
import unittest
from collections import Counter

from scrutateur.boucle import Scrutateur
from scrutateur.config import Reglages
from tests.fakes import FauxDepot, instance, lecture_vide


def reglages(intervalle=60.0, parallele=16):
    return Reglages(stockage_dsn="postgresql://x", intervalle_s=intervalle, max_parallele=parallele)


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


if __name__ == "__main__":
    unittest.main()
