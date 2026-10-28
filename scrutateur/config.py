"""Reglages du scrutateur, lus dans les variables d'environnement (jamais dans Git).

En service : le fichier /etc/scrutateur/scrutateur.env (mode 0600, proprietaire root) charge par systemd.
Modele sans secret : scrutateur/deploy/scrutateur.env.example
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping


class ErreurConfiguration(Exception):
    pass


@dataclass(frozen=True)
class Reglages:
    stockage_dsn: str = field(repr=False)  # base meteo (pg01) ; contient le mot de passe du role scrutateur
    intervalle_s: float = 60.0
    max_parallele: int = 16
    cible_connexion_timeout_s: int = 10  # delai de connexion a une instance surveillee
    cible_requete_timeout_s: int = 15  # delai de chaque requete sur une instance surveillee
    cible_sslmode: str = "prefer"

    @classmethod
    def depuis_env(cls, env: Mapping[str, str] | None = None) -> "Reglages":
        env = os.environ if env is None else env
        dsn = env.get("SCRUTATEUR_STOCKAGE_DSN", "").strip()
        if not dsn:
            raise ErreurConfiguration(
                "SCRUTATEUR_STOCKAGE_DSN est obligatoire, ex. postgresql://scrutateur:...@pg01:5432/meteo"
            )
        r = cls(
            stockage_dsn=dsn,
            intervalle_s=_nombre(env, "SCRUTATEUR_INTERVALLE_S", 60.0, float),
            max_parallele=_nombre(env, "SCRUTATEUR_MAX_PARALLELE", 16, int),
            cible_connexion_timeout_s=_nombre(env, "SCRUTATEUR_CIBLE_CONNEXION_TIMEOUT_S", 10, int),
            cible_requete_timeout_s=_nombre(env, "SCRUTATEUR_CIBLE_REQUETE_TIMEOUT_S", 15, int),
            cible_sslmode=env.get("SCRUTATEUR_CIBLE_SSLMODE", "prefer").strip() or "prefer",
        )
        r.verifier()
        return r

    def verifier(self) -> None:
        if self.intervalle_s < 5:
            raise ErreurConfiguration("SCRUTATEUR_INTERVALLE_S doit etre >= 5 secondes")
        if self.max_parallele < 1:
            raise ErreurConfiguration("SCRUTATEUR_MAX_PARALLELE doit etre >= 1")
        if self.cible_connexion_timeout_s < 1 or self.cible_requete_timeout_s < 1:
            raise ErreurConfiguration("Les delais de connexion et de requete (cible) doivent etre >= 1 seconde")
        if self.cible_sslmode not in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
            raise ErreurConfiguration("SCRUTATEUR_CIBLE_SSLMODE : disable, allow, prefer, require, verify-ca ou verify-full")

    @property
    def pire_duree_releve_s(self) -> int:
        """Duree maximale d'un releve : connexion + deux requetes (controle des droits, tableau des sessions)."""
        return self.cible_connexion_timeout_s + 2 * self.cible_requete_timeout_s


def _nombre(env: Mapping[str, str], cle: str, defaut, type_):
    brut = env.get(cle)
    if brut is None or not brut.strip():
        return defaut
    try:
        return type_(brut.strip())
    except ValueError:
        raise ErreurConfiguration(f"{cle} : valeur numerique attendue, recu {brut!r}") from None
