"""Point d'entree : python -m scrutateur [--une-fois] [--tester NOM] [-v]"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from dataclasses import asdict

from .cible import creer_source_pg
from .boucle import Scrutateur
from .config import ErreurConfiguration, Reglages
from .indicateurs import calculer_indicateurs
from .store import Depot

journal = logging.getLogger("scrutateur")


def lire_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="scrutateur", description=__doc__)
    p.add_argument("--une-fois", action="store_true", help="un seul cycle (toutes les instances), puis quitter")
    p.add_argument(
        "--tester", metavar="NOM",
        help="releve l'instance NOM, affiche les indicateurs et quitte, sans rien ecrire dans PostgreSQL",
    )
    p.add_argument("-v", "--verbose", action="store_true", help="journal detaille")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = lire_arguments(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s : %(message)s",
        stream=sys.stderr,
    )
    try:
        reglages = Reglages.depuis_env()
    except ErreurConfiguration as exc:
        journal.error("Configuration invalide : %s", exc)
        return 2

    depot = Depot(reglages.stockage_dsn)
    source = creer_source_pg(reglages)

    if args.tester:
        return _tester(args.tester, depot, source)

    if reglages.pire_duree_releve_s >= reglages.intervalle_s:
        journal.warning(
            "Un releve peut durer jusqu'a %d s (connexion + 2 requetes) pour un intervalle de %.0f s : "
            "reduire les delais (SCRUTATEUR_CIBLE_*)", reglages.pire_duree_releve_s, reglages.intervalle_s,
        )

    arret = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: arret.set())

    journal.info("Demarrage : intervalle %.0f s, %d releve(s) en parallele maximum", reglages.intervalle_s, reglages.max_parallele)
    Scrutateur(reglages, depot, source).executer(arret, une_fois=args.une_fois)
    journal.info("Arret")
    return 0


def _tester(nom: str, depot: Depot, source) -> int:
    try:
        instances = {i.nom: i for i in depot.lire_instances()}
    except Exception as exc:  # noqa: BLE001
        # Le texte de l'exception n'est pas affiche : une URL mal formee peut y laisser un morceau du mot de passe.
        journal.error("Connexion a PostgreSQL impossible (%s). Verifier SCRUTATEUR_STOCKAGE_DSN : hote, mot de passe, et "
                      "caracteres speciaux du mot de passe a ecrire en %%XX (docs/scrutateur.md 3.3).", type(exc).__name__)
        return 1
    if nom not in instances:
        journal.error("Instance %r absente ou inactive dans meteo.instance (connues : %s)", nom, ", ".join(sorted(instances)) or "aucune")
        return 1
    try:
        indicateurs = calculer_indicateurs(source(instances[nom]))
    except Exception as exc:  # noqa: BLE001
        from .collecte import message_erreur

        journal.error("%s : %s", nom, message_erreur(exc, instances[nom]))
        return 1
    print(json.dumps(asdict(indicateurs), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
