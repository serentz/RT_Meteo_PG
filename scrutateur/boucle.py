"""Boucle du scrutateur : un cycle par intervalle (60 s), toutes les instances en parallele.

A chaque cycle la liste des instances est relue dans PostgreSQL : une instance ajoutee, modifiee ou
desactivee dans meteo.instance est prise en compte au cycle suivant, sans redemarrer le service.
Une instance dont le releve precedent n'est pas termine (reseau bloque...) n'est pas relancee : ses
releves ne s'empilent pas, et son etat passe a 'inconnu' par peremption (voir meteo.parametre).

Passage a l'echelle (100 ou 200 instances) :
- etalement : les releves d'un cycle ne partent pas tous a la meme seconde mais sont repartis regulierement
  sur `etalement_s` secondes (evite la rafale de connexions et reduit le nombre de threads necessaires) ;
- partition : plusieurs scrutateurs peuvent tourner cote a cote ; le scrutateur i/N ne prend que les instances
  dont instance_id % N == i. Chaque instance est relevee par un seul scrutateur, aucune n'est oubliee.
"""
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Callable, Dict, List, Optional

from .cible import Source
from .collecte import DepotEcriture, collecter_et_enregistrer
from .config import Reglages
from .modeles import Instance

journal = logging.getLogger("scrutateur.boucle")


class Depot(DepotEcriture):
    def lire_instances(self) -> List[Instance]: ...


class Scrutateur:
    def __init__(
        self,
        reglages: Reglages,
        depot: Depot,
        source: Source,
        horloge: Callable[[], float] = time.monotonic,
    ):
        self._reglages = reglages
        self._depot = depot
        self._source = source
        self._horloge = horloge
        self._en_cours: Dict[int, Future] = {}
        self._pool: Optional[ThreadPoolExecutor] = None

    def instances_de_la_partition(self, instances: List[Instance]) -> List[Instance]:
        """Les instances de ce scrutateur (instance_id % N == i), triees par identifiant."""
        r = self._reglages
        return sorted((i for i in instances if i.instance_id % r.partition_total == r.partition_index),
                      key=lambda i: i.instance_id)

    def lancer_cycle(self, arret: Optional[threading.Event] = None, etaler: bool = False) -> List[Future]:
        """Lance le releve de chaque instance de la partition, en parallele. Rend les taches lancees (sans les attendre).

        etaler : le releve de la k-ieme instance (sur n) part a k/n * etalement_s apres le debut du cycle.
        """
        assert self._pool is not None, "lancer_cycle() s'utilise depuis executer()"
        debut = self._horloge()
        try:
            toutes = self._depot.lire_instances()
        except Exception as exc:  # noqa: BLE001 - PostgreSQL indisponible : on reessaie au cycle suivant
            journal.error("Lecture de meteo.instance impossible : %s", exc)
            return []

        instances = self.instances_de_la_partition(toutes)
        if not toutes:
            journal.warning("Aucune instance actif dans meteo.instance")
        actifs = {i.instance_id for i in instances}
        for disparu in set(self._en_cours) - actifs:
            if self._en_cours[disparu].done():
                del self._en_cours[disparu]

        lancees: List[Future] = []
        file_saturee = False
        for rang, instance in enumerate(instances):
            if etaler and self._reglages.etalement_s > 0 and arret is not None:
                attente = debut + rang / len(instances) * self._reglages.etalement_s - self._horloge()
                if attente > 0 and arret.wait(attente):
                    break  # arret demande pendant l'etalement
            precedente = self._en_cours.get(instance.instance_id)
            if precedente is not None and not precedente.done():
                journal.warning("%s : releve precedent toujours en cours, cycle ignore", instance.nom)
                continue
            tache = self._pool.submit(collecter_et_enregistrer, instance, self._source, self._depot)
            self._en_cours[instance.instance_id] = tache
            lancees.append(tache)
            en_cours = sum(1 for f in self._en_cours.values() if not f.done())
            if en_cours > self._reglages.max_parallele and not file_saturee:
                file_saturee = True
                journal.warning(
                    "%d releves en cours pour %d thread(s) : des releves attendent un thread. Augmenter "
                    "SCRUTATEUR_MAX_PARALLELE ou ajouter un scrutateur (SCRUTATEUR_PARTITION).",
                    en_cours, self._reglages.max_parallele,
                )
        journal.info("Cycle (partition %d/%d) : %d instance(s) lancee(s) sur %d", self._reglages.partition_index,
                     self._reglages.partition_total, len(lancees), len(instances))
        return lancees

    def executer(self, arret: threading.Event, une_fois: bool = False) -> None:
        """Boucle jusqu'a ce que `arret` soit positionne. une_fois : un seul cycle, puis attend sa fin."""
        pool = ThreadPoolExecutor(max_workers=self._reglages.max_parallele, thread_name_prefix="cible")
        self._pool = pool
        try:
            prochain = self._horloge()
            while not arret.is_set():
                lancees = self.lancer_cycle(arret, etaler=not une_fois)
                if une_fois:
                    wait(lancees)
                    break
                prochain += self._reglages.intervalle_s
                maintenant = self._horloge()
                if prochain <= maintenant:  # cycle en retard : on repart de maintenant, sans rattraper
                    journal.warning("Cycle en retard de %.1f s", maintenant - prochain)
                    prochain = maintenant + self._reglages.intervalle_s
                arret.wait(prochain - maintenant)
        finally:
            for tache in list(self._en_cours.values()):  # les releves encore en attente ne demarrent pas (Python < 3.9 : pas de cancel_futures)
                tache.cancel()
            pool.shutdown(wait=True)  # les releves en cours se terminent (delais bornes)
            self._pool = None
