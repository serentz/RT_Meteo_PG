"""Lecture d'une instance PostgreSQL surveillee, a distance (port 5432 par defaut), depuis le bastion.

UNE requete sur pg_stat_activity (+ pg_blocking_pids) : le tableau obtenu est lu en memoire, les indicateurs en sont
calcules (indicateurs.py) et il est conserve tel quel dans meteo.processus. Elle est reproduite a l'identique dans
sql/cible/supervision.sql pour l'essayer sous psql. Aucune extension, aucun compteur cumulatif : rien n'est remis
a zero sur l'instance. Le texte des requetes n'est jamais lu (seul son premier mot).

Un controle prealable (tres leger) verifie que le login voit toutes les sessions (pg_monitor ou superutilisateur) :
sans cela PostgreSQL masque les sessions des autres utilisateurs et le tableau serait faussement vide.
Le pilote (psycopg 3) est charge a la demande : le reste du scrutateur et ses tests n'en ont pas besoin.
"""
from __future__ import annotations

from typing import Callable

from .config import Reglages
from .modeles import Instance, Lecture, LigneProcessus

SQL_PROCESSUS = """\
WITH s AS (
    SELECT a.*, pg_blocking_pids(a.pid) AS bloqueurs
    FROM pg_stat_activity a
    WHERE a.backend_type = 'client backend' AND a.pid <> pg_backend_pid()
)
SELECT s.pid,
       s.usename AS login,
       s.datname AS base,
       s.state AS statut,
       s.application_name AS programme,
       COALESCE(host(s.client_addr), 'local') AS hote,
       CASE WHEN s.wait_event_type IS NOT NULL THEN s.wait_event_type || ':' || COALESCE(s.wait_event, '') END AS attente,
       upper(split_part(ltrim(s.query), ' ', 1)) AS cmd,
       COALESCE(s.bloqueurs[1], 0) AS bloqueur_pid,
       CASE WHEN cardinality(s.bloqueurs) > 0 THEN floor(extract(epoch FROM now() - s.query_start))::int END AS blocage_s,
       CASE WHEN s.state = 'active' THEN floor(extract(epoch FROM now() - s.query_start))::int END AS execution_s,
       CASE WHEN s.xact_start IS NOT NULL THEN floor(extract(epoch FROM now() - s.xact_start))::int END AS transaction_s,
       to_char(s.xact_start, 'YYYY-MM-DD HH24:MI:SS') AS transaction_debut
FROM s
WHERE s.state = 'active'
   OR s.xact_start IS NOT NULL
   OR cardinality(s.bloqueurs) > 0
   OR s.pid IN (SELECT unnest(b.bloqueurs) FROM s b)
ORDER BY s.pid"""

# Le login voit-il toutes les sessions ? (superutilisateur, ou membre de pg_monitor / pg_read_all_stats)
SQL_DROITS = """\
SELECT COALESCE((SELECT rolsuper FROM pg_roles WHERE rolname = current_user), false)
       OR pg_has_role(current_user, 'pg_read_all_stats', 'USAGE')"""

# Fonction qui interroge une instance et rend sa lecture brute (ou leve une exception).
Source = Callable[[Instance], Lecture]


class DroitsInsuffisants(Exception):
    pass


def creer_source_pg(reglages: Reglages) -> Source:
    """Source de production : psycopg 3, connexion en lecture seule, en autocommit, avec delais."""

    def lire(instance: Instance) -> Lecture:
        import psycopg  # import tardif : absent des postes de test

        # autocommit + lecture seule : la connexion du scrutateur ne laisse jamais de transaction ouverte ni
        # de verrou sur l'instance surveillee. statement_timeout borne chaque requete cote serveur.
        options = (
            f"-c statement_timeout={reglages.cible_requete_timeout_s * 1000} "
            "-c default_transaction_read_only=on -c idle_in_transaction_session_timeout=0"
        )
        with psycopg.connect(
            host=instance.hote,
            port=instance.port,
            dbname=instance.base,
            user=instance.login,
            password=instance.password,
            connect_timeout=reglages.cible_connexion_timeout_s,
            application_name="scrutateur",
            sslmode=reglages.cible_sslmode,
            options=options,
            autocommit=True,
        ) as conn:
            voit_tout = conn.execute(SQL_DROITS).fetchone()
            if not voit_tout or not voit_tout[0]:
                raise DroitsInsuffisants(
                    f"le login {instance.login!r} doit etre membre de pg_monitor "
                    f"(GRANT pg_monitor TO {instance.login};), sinon PostgreSQL masque les sessions des autres utilisateurs"
                )
            lignes = conn.execute(SQL_PROCESSUS).fetchall()
        return Lecture(processus=[ligne_processus(r) for r in lignes])

    return lire


def ligne_processus(r) -> LigneProcessus:
    """Une ligne de SQL_PROCESSUS (dans l'ordre des colonnes) vers LigneProcessus."""
    return LigneProcessus(
        pid=int(r[0]),
        login=_texte(r[1]),
        base=_texte(r[2]),
        statut=_texte(r[3]),
        programme=_texte(r[4]),
        hote=_texte(r[5]),
        attente=_texte(r[6]),
        cmd=_texte(r[7]),
        bloqueur_pid=_entier(r[8]) or 0,
        blocage_s=_entier(r[9]),
        execution_s=_entier(r[10]),
        transaction_s=_entier(r[11]),
        transaction_debut=_texte(r[12]),
    )


def _entier(valeur) -> int | None:
    return None if valeur is None else int(float(valeur))


def _texte(valeur) -> str | None:
    return None if valeur is None else str(valeur).strip()
