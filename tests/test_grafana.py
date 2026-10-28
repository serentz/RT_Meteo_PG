import json
import pathlib
import re
import unittest

RACINE = pathlib.Path(__file__).resolve().parent.parent / "grafana"


def tableaux_de_bord():
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (RACINE / "dashboards").glob("*.json")}


def requetes(db):
    return [t["rawSql"] for p in db["panels"] for t in p["targets"]] + [
        v["query"] for v in db["templating"]["list"]]


class TestGrafana(unittest.TestCase):
    def test_deux_tableaux_de_bord_json_valides_avec_uid_unique(self):
        dbs = tableaux_de_bord()
        self.assertEqual(sorted(dbs), ["detail.json", "liste.json", "synthese.json"])
        self.assertEqual(len({d["uid"] for d in dbs.values()}), 3)

    def test_les_liens_pointent_vers_les_uid_existants(self):
        dbs = tableaux_de_bord()
        uids = {d["uid"] for d in dbs.values()}
        texte = json.dumps(dbs)
        for uid in re.findall(r"/d/([a-z-]+)", texte):
            self.assertIn(uid, uids)

    def test_datasource_coherente_avec_le_provisioning(self):
        prov = (RACINE / "provisioning" / "datasources" / "meteo.yaml").read_text(encoding="utf-8")
        self.assertIn("uid: meteo-pg", prov)
        self.assertIn("$__env{METEO_GRAFANA_PWD}", prov)  # jamais de mot de passe en clair
        for db in tableaux_de_bord().values():
            for p in db["panels"]:
                self.assertEqual(p["datasource"]["uid"], "meteo-pg")
                self.assertTrue(all(t["datasource"]["uid"] == "meteo-pg" for t in p["targets"]))

    def test_les_requetes_ne_lisent_que_les_objets_autorises_a_grafana_ro(self):
        roles = (RACINE.parent / "sql" / "stockage" / "002_roles.sql").read_text(encoding="utf-8")
        for db in tableaux_de_bord().values():
            for sql in requetes(db):
                for objet in re.findall(r"meteo\.(\w+)", sql):
                    self.assertIn("meteo." + objet, roles, f"{objet} non accorde a grafana_ro")
                self.assertNotRegex(sql.lower(), r"\b(password|login)\b\s*(,|from)", "colonne interdite")
                self.assertNotIn("meteo.instance i", sql.replace("JOIN meteo.instance i USING", ""))

    def test_les_icones_referencees_existent(self):
        images = RACINE.parent / "images" / "iconnes"
        for db in tableaux_de_bord().values():
            for sql in requetes(db):
                for png in re.findall(r"'([A-Za-z_]+\.png)'", sql):
                    self.assertTrue((images / png).is_file(), png)


if __name__ == "__main__":
    unittest.main()
