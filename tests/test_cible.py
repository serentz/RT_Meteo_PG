import sys
import types
import unittest
from unittest import mock

from scrutateur import cible
from scrutateur.config import Reglages
from tests.fakes import instance

REGLAGES = Reglages(stockage_dsn="postgresql://x")

# Ordre des colonnes de SQL_PROCESSUS :
# pid, login, base, statut, programme, hote, attente, cmd, bloqueur_pid, blocage_s, execution_s, transaction_s, transaction_debut
LIGNE_ACTIVE = (2190, "app_svc", "erp", "active", "psql", "10.0.0.5", "IO:DataFileRead", "SELECT", 0, None, 4, 4, "2026-10-28 09:00:00")
LIGNE_BLOQUEE = (2200, "batch", "erp", "active", "appli", "10.0.0.6", "Lock:transactionid", "UPDATE", 2210, 45, 45, 120, "2026-10-28 08:58:00")
LIGNE_BLOQUEUR = (2210, "batch", "erp", "idle in transaction", "appli", "10.0.0.6", "Client:ClientRead", "UPDATE", 0, None, None, 300, "2026-10-28 08:55:00")


class FauxResultat:
    def __init__(self, lignes):
        self.lignes = lignes

    def fetchone(self):
        return self.lignes[0] if self.lignes else None

    def fetchall(self):
        return self.lignes


class FausseConnexion:
    def __init__(self, lignes, droits=True):
        self.lignes, self.droits, self.executes, self.fermee = lignes, droits, [], False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fermee = True

    def execute(self, sql):
        self.executes.append(sql)
        return FauxResultat([(self.droits,)] if sql == cible.SQL_DROITS else self.lignes)


def faux_psycopg(connexion, appels):
    def connect(**kwargs):
        appels.append(kwargs)
        return connexion

    return types.SimpleNamespace(connect=connect)


class TestLigneProcessus(unittest.TestCase):
    def test_conversion_d_une_ligne_active(self):
        lp = cible.ligne_processus(LIGNE_ACTIVE)
        self.assertEqual((lp.pid, lp.login, lp.base, lp.statut), (2190, "app_svc", "erp", "active"))
        self.assertEqual((lp.hote, lp.programme, lp.attente, lp.cmd), ("10.0.0.5", "psql", "IO:DataFileRead", "SELECT"))
        self.assertEqual((lp.bloqueur_pid, lp.blocage_s, lp.execution_s, lp.transaction_s), (0, None, 4, 4))
        self.assertEqual(lp.transaction_debut, "2026-10-28 09:00:00")

    def test_conversion_d_une_ligne_bloquee_et_d_un_bloqueur_inactif(self):
        bloquee = cible.ligne_processus(LIGNE_BLOQUEE)
        self.assertEqual((bloquee.bloqueur_pid, bloquee.blocage_s, bloquee.execution_s), (2210, 45, 45))
        bloqueur = cible.ligne_processus(LIGNE_BLOQUEUR)
        self.assertEqual((bloqueur.bloqueur_pid, bloqueur.execution_s, bloqueur.transaction_s), (0, None, 300))

    def test_valeurs_null(self):
        lp = cible.ligne_processus((5,) + (None,) * 12)
        self.assertEqual((lp.pid, lp.login, lp.bloqueur_pid, lp.execution_s, lp.transaction_s), (5, None, 0, None, None))


class TestSourcePg(unittest.TestCase):
    def lire(self, lignes, droits=True):
        connexion, appels = FausseConnexion(lignes, droits), []
        with mock.patch.dict(sys.modules, {"psycopg": faux_psycopg(connexion, appels)}):
            lecture = cible.creer_source_pg(REGLAGES)(instance(1))
        return lecture, connexion, appels

    def test_controle_des_droits_puis_une_requete_connexion_fermee(self):
        lecture, connexion, _ = self.lire([LIGNE_ACTIVE, LIGNE_BLOQUEE, LIGNE_BLOQUEUR])
        self.assertEqual(connexion.executes, [cible.SQL_DROITS, cible.SQL_PROCESSUS])
        self.assertTrue(connexion.fermee)
        self.assertEqual([p.pid for p in lecture.processus], [2190, 2200, 2210])

    def test_droits_insuffisants_leve_une_erreur_explicite(self):
        connexion = FausseConnexion([LIGNE_ACTIVE], droits=False)
        with mock.patch.dict(sys.modules, {"psycopg": faux_psycopg(connexion, [])}):
            with self.assertRaises(cible.DroitsInsuffisants) as ctx:
                cible.creer_source_pg(REGLAGES)(instance(1))
        self.assertIn("pg_monitor", str(ctx.exception))
        self.assertEqual(connexion.executes, [cible.SQL_DROITS])  # la requete principale n'est pas lancee
        self.assertTrue(connexion.fermee)

    def test_connexion_en_autocommit_lecture_seule_avec_delais(self):
        _, _, appels = self.lire([])
        kw = appels[0]
        self.assertTrue(kw["autocommit"])
        self.assertEqual(kw["connect_timeout"], REGLAGES.cible_connexion_timeout_s)
        self.assertEqual((kw["host"], kw["port"], kw["dbname"], kw["application_name"]), ("pg02", 5432, "postgres", "scrutateur"))
        self.assertIn("default_transaction_read_only=on", kw["options"])
        self.assertIn("statement_timeout=15000", kw["options"])

    def test_connexion_fermee_meme_si_la_requete_echoue(self):
        connexion = FausseConnexion([])
        connexion.execute = mock.Mock(side_effect=RuntimeError("permission denied"))
        with mock.patch.dict(sys.modules, {"psycopg": faux_psycopg(connexion, [])}):
            with self.assertRaises(RuntimeError):
                cible.creer_source_pg(REGLAGES)(instance(1))
        self.assertTrue(connexion.fermee)


if __name__ == "__main__":
    unittest.main()
