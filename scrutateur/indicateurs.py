"""Calcul des indicateurs a partir du tableau des sessions lu sur l'instance. Fonctions pures, sans acces reseau.

Definitions (docs/architecture.md) :
- blocage : session bloquee par une autre (bloqueur_pid <> 0) ; duree = blocage_s (secondes).
  Max et moyenne portent sur les seules sessions actuellement bloquees ; aucune bloquee donne 0.
- requete : session dont l'instruction est en cours (state = 'active', execution_s non NULL) ; duree = execution_s.
  Max et moyenne portent sur ces sessions (bloquees comprises) ; aucune donne 0.
- transaction : session avec une transaction ouverte (transaction_s non NULL, y compris 'idle in transaction') ;
  l'indicateur est la plus longue ; aucune donne 0. Une transaction peut etre longue sans bloquer personne.
- Un bloqueur inactif figure dans le tableau (la requete SQL le retient) mais n'entre ni dans les blocages ni dans
  les requetes ; il entre dans les transactions s'il en a une. La connexion du scrutateur et les processus internes
  de PostgreSQL sont deja exclus par la requete SQL (voir cible.py).
- Le detail conserve au plus MAX_DETAILS lignes (bloquees, puis transactions et requetes les plus longues d'abord) ;
  les indicateurs, eux, portent sur toutes les lignes lues.
"""
from __future__ import annotations

from .modeles import Indicateurs, Lecture, LigneProcessus

MAX_DETAILS = 200


def calculer_indicateurs(lecture: Lecture) -> Indicateurs:
    # Un pid ne doit apparaitre qu'une fois (cle primaire du detail en base) : la derniere ligne l'emporte.
    par_pid = {p.pid: p for p in lecture.processus}
    lignes = [par_pid[pid] for pid in sorted(par_pid)]

    durees_blocage = [max(p.blocage_s or 0, 0) for p in lignes if p.bloqueur_pid]
    durees_requete = [max(p.execution_s, 0) for p in lignes if p.execution_s is not None]
    durees_transaction = [max(p.transaction_s, 0) for p in lignes if p.transaction_s is not None]

    return Indicateurs(
        nb_bloques=len(durees_blocage),
        blocage_max_s=float(max(durees_blocage, default=0)),
        blocage_moyen_s=_moyenne(durees_blocage),
        nb_requetes=len(durees_requete),
        requete_max_s=float(max(durees_requete, default=0)),
        requete_moyenne_s=_moyenne(durees_requete),
        details=sorted(lignes, key=_priorite)[:MAX_DETAILS],
        nb_transactions=len(durees_transaction),
        transaction_max_s=float(max(durees_transaction, default=0)),
    )


def _priorite(p: LigneProcessus) -> tuple:
    """Ordre du detail : les plus ennuyeuses d'abord (bloquees, transactions longues, requetes longues), puis par pid."""
    return (-(p.blocage_s or 0), -(p.transaction_s or 0), -(p.execution_s or 0), p.pid)


def _moyenne(valeurs: list[int]) -> float:
    return round(sum(valeurs) / len(valeurs), 1) if valeurs else 0.0
