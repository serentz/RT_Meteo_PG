"""Structures de donnees echangees entre les modules du scrutateur."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Instance:
    """Une ligne de meteo.instance. Le mot de passe n'apparait jamais dans repr() ni dans les journaux."""

    instance_id: int
    nom: str
    login: str
    password: str = field(repr=False)
    host: Optional[str] = None
    port: int = 5432
    base: str = "postgres"  # base de donnees de connexion (pg_stat_activity est commun a toute l'instance)

    @property
    def hote(self) -> str:
        """Machine a joindre : host si renseigne, sinon le nom de l'instance."""
        return self.host or self.nom


@dataclass(frozen=True)
class LigneProcessus:
    """Une session cliente de l'instance surveillee, lue dans pg_stat_activity (voir sql/cible/supervision.sql)."""

    pid: int
    statut: Optional[str]  # state : active, idle in transaction...
    cmd: Optional[str]  # premier mot de la derniere requete (SELECT, UPDATE...) ; le texte complet n'est jamais lu
    login: Optional[str]
    bloqueur_pid: int  # premier bloqueur (pg_blocking_pids) ; 0 si la session n'est pas bloquee
    blocage_s: Optional[int] = None  # secondes depuis le debut de l'instruction bloquee ; None si pas bloquee
    execution_s: Optional[int] = None  # secondes depuis le debut de l'instruction ; None si la session n'est pas active
    transaction_s: Optional[int] = None  # secondes depuis le debut de la transaction ouverte ; None s'il n'y en a pas
    transaction_debut: Optional[str] = None  # heure du serveur surveille, 'AAAA-MM-JJ HH:MM:SS'
    base: Optional[str] = None  # datname
    hote: Optional[str] = None  # client_addr ('local' pour une connexion par socket)
    programme: Optional[str] = None  # application_name
    attente: Optional[str] = None  # wait_event_type:wait_event


@dataclass(frozen=True)
class Lecture:
    """Resultat brut d'une interrogation d'une instance : le tableau des sessions retenues, tel quel."""

    processus: List[LigneProcessus]


@dataclass(frozen=True)
class Indicateurs:
    """Indicateurs calcules sur le tableau en memoire, et ce tableau (une session par ligne, par pid)."""

    nb_bloques: int
    blocage_max_s: float
    blocage_moyen_s: float
    nb_requetes: int
    requete_max_s: float
    requete_moyenne_s: float
    details: List[LigneProcessus]
    nb_transactions: int = 0
    transaction_max_s: float = 0.0  # plus longue transaction ouverte (0 s'il n'y en a aucune)


@dataclass(frozen=True)
class Mesure:
    """Resultat d'un releve, pret a etre ecrit par meteo.enregistrer_mesure."""

    instance_id: int
    statut: str  # 'ok' | 'erreur'
    duree_ms: int
    erreur: Optional[str] = None
    indicateurs: Optional[Indicateurs] = None
