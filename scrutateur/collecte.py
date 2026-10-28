"""Unite de travail du scrutateur : releve d'UNE instance et mise a jour de PostgreSQL.

collecter_et_enregistrer() est la fonction appelee, en parallele, pour chaque ligne de meteo.instance.
Elle ne leve jamais d'exception : un echec (instance injoignable, login refuse, requete trop lente...)
est enregistre comme une mesure 'erreur', ce qui donne l'etat 'inconnu' cote affichage, et n'empeche pas
les autres instances d'etre relevees.
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Protocol

from .cible import Source
from .indicateurs import calculer_indicateurs
from .modeles import Instance, Mesure

journal = logging.getLogger("scrutateur.collecte")

LONGUEUR_MAX_ERREUR = 500


class DepotEcriture(Protocol):
    def enregistrer(self, mesure: Mesure) -> None: ...


def collecter_et_enregistrer(
    instance: Instance,
    source: Source,
    depot: DepotEcriture,
    horloge: Callable[[], float] = time.monotonic,
) -> Mesure:
    debut = horloge()
    try:
        indicateurs = calculer_indicateurs(source(instance))
        mesure = Mesure(instance.instance_id, "ok", _duree_ms(debut, horloge), indicateurs=indicateurs)
        journal.debug(
            "%s : %d bloque(s) (max %.0f s), %d requete(s) en cours (max %.0f s), %d transaction(s) (max %.0f s)",
            instance.nom, indicateurs.nb_bloques, indicateurs.blocage_max_s,
            indicateurs.nb_requetes, indicateurs.requete_max_s,
            indicateurs.nb_transactions, indicateurs.transaction_max_s,
        )
    except Exception as exc:  # noqa: BLE001 - toute panne de l'instance devient une mesure 'erreur'
        message = message_erreur(exc, instance)
        journal.warning("%s : releve en erreur : %s", instance.nom, message)
        mesure = Mesure(instance.instance_id, "erreur", _duree_ms(debut, horloge), erreur=message)

    try:
        depot.enregistrer(mesure)
    except Exception as exc:  # noqa: BLE001 - PostgreSQL indisponible : rien a ecrire, on le journalise
        journal.error("%s : ecriture PostgreSQL impossible : %s", instance.nom, message_erreur(exc, instance))
    return mesure


def message_erreur(exc: BaseException, instance: Instance) -> str:
    """Message sur une ligne, sans le mot de passe, tronque."""
    texte = f"{type(exc).__name__}: {exc}"
    if instance.password:
        texte = texte.replace(instance.password, "***")
    texte = " ".join(texte.split())
    return texte[:LONGUEUR_MAX_ERREUR]


def _duree_ms(debut: float, horloge: Callable[[], float]) -> int:
    return max(0, int((horloge() - debut) * 1000))
