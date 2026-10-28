"""Faux composants pour tester le scrutateur sans PostgreSQL."""
from __future__ import annotations

import threading

from scrutateur.modeles import Instance, Lecture


def instance(i: int, nom: str | None = None, password: str = "s3cret") -> Instance:
    return Instance(instance_id=i, nom=nom or f"pg{i + 1:02d}", login="scrutateur", password=password, host="pg02")


class FauxDepot:
    """Depot en memoire : instances lisibles, mesures enregistrees, pannes simulables."""

    def __init__(self, instances=None):
        self.instances = list(instances or [])
        self.ecrites = []
        self.panne_lecture = False
        self.panne_ecriture = False
        self._verrou = threading.Lock()

    def lire_instances(self):
        if self.panne_lecture:
            raise ConnectionError("pg01 injoignable")
        with self._verrou:
            return list(self.instances)

    def enregistrer(self, mesure):
        if self.panne_ecriture:
            raise ConnectionError("pg01 injoignable")
        with self._verrou:
            self.ecrites.append(mesure)

    def pour(self, instance_id):
        with self._verrou:
            return [m for m in self.ecrites if m.instance_id == instance_id]


def lecture_vide() -> Lecture:
    return Lecture(processus=[])
