# Scrutateur : installation, exploitation, tests

Le scrutateur est le script Python du bastion. Chaque minute il lit `meteo.instance` dans le PostgreSQL de stockage (pg01), interroge en parallèle chaque instance PostgreSQL active (par exemple pg02) et enregistre le résultat par `meteo.enregistrer_mesure(...)`. Règles et indicateurs : [architecture](architecture.md).

**Deux rôles différents pour PostgreSQL, à ne pas confondre :**

- **stockage** : pg01, base `meteo` ; contient le schéma `meteo` (instances à surveiller, mesures, seuils) ; Grafana la lit ;
- **instance surveillée** : pg02 (et toute autre instance déclarée dans `meteo.instance`) ; le scrutateur s'y connecte à distance avec un login `scrutateur` membre de `pg_monitor`, rien n'y est installé.

## Avant de commencer : où taper quoi

Chaque bloc de commandes de ce document est précédé de la **machine** sur laquelle le taper. Une commande tapée au mauvais endroit échoue ou ne fait rien. Les invites (le texte affiché avant le curseur) indiquent où l'on est :

| Où | Comment s'y connecter | Invite affichée | Pour en sortir |
|---|---|---|---|
| PowerShell, sur le PC Windows | menu Démarrer, « PowerShell » | `PS I:\POC\RT_Meteo_PG>` | fermer la fenêtre |
| VM `pg01` (Ubuntu, stockage) | depuis PowerShell : `ssh admin01@192.168.50.11` | `admin01@pg01:~$` | `exit` |
| VM `pg02` (Ubuntu, instance surveillée) | depuis PowerShell : `ssh admin01@192.168.50.21` | `admin01@pg02:~$` | `exit` |
| VM `bastion` (Ubuntu) | depuis PowerShell : `ssh admin01@192.168.50.10` | `admin01@bastion:~$` | `exit` |
| Console `psql` sur pg01 (stockage) | sur pg01 : `sudo -u postgres psql -d meteo` | `meteo=#` | `\q` |
| Console `psql` sur pg02 (surveillé) | sur pg02 : `sudo -u postgres psql` | `postgres=#` | `\q` |

- Le mot de passe de `ssh` et de `sudo` est celui choisi pour `admin01` au lancement de `create_vms.ps1`.
- À la première connexion à une VM, `ssh` affiche une empreinte et demande `Are you sure you want to continue connecting`. Répondre `yes`.
- Dans une console PostgreSQL, chaque instruction SQL se termine par `;`.
- Copier-coller dans PowerShell : clic droit. Une ligne de bloc = une commande, sauf les lignes qui se terminent par `\` (la commande continue sur la ligne suivante).

Trois mots de passe sont à choisir et sont désignés ainsi dans le document :

| Nom | Sert à |
|---|---|
| `MOT_DE_PASSE_1` | rôle `scrutateur` de la base de stockage (pg01), utilisé par le script |
| `MOT_DE_PASSE_2` | rôle `grafana_ro` de la base de stockage (pg01), utilisé par Grafana |
| `MOT_DE_PASSE_CIBLE` | login `scrutateur` de l'instance surveillée (pg02) |

Éviter l'apostrophe et l'antislash dans ces mots de passe.

## 1. PostgreSQL de stockage sur pg01

### 1.1 Envoyer les scripts SQL sur pg01 (PowerShell, sur Windows)

Dans `I:\POC\RT_Meteo_PG`, après un `git pull --ff-only` :

```powershell
scp -r I:\POC\RT_Meteo_PG\sql admin01@192.168.50.11:/tmp/
```

### 1.2 Installer PostgreSQL et créer la base de stockage (sur pg01)

Se connecter : `ssh admin01@192.168.50.11`. Puis :

```bash
sudo apt update
sudo apt install -y postgresql
psql --version
sudo -u postgres createdb meteo
sudo -u postgres psql -d meteo -v ON_ERROR_STOP=1 -f /tmp/sql/stockage/001_schema.sql
sudo -u postgres psql -d meteo -v ON_ERROR_STOP=1 \
  -v pwd_scrutateur='MOT_DE_PASSE_1' -v pwd_grafana='MOT_DE_PASSE_2' -f /tmp/sql/stockage/002_roles.sql
```

- `psql --version` doit afficher PostgreSQL **15 ou plus** (Ubuntu 24.04 installe la 16) : le schéma utilise `UNIQUE NULLS NOT DISTINCT`.
- Remplacer `MOT_DE_PASSE_1` et `MOT_DE_PASSE_2` par les mots de passe choisis, en gardant les apostrophes.
- Pourquoi `sudo -u postgres` et pas simplement `psql` : sans option, `psql` se connecte avec le nom de l'utilisateur Linux (`admin01`) et PostgreSQL répond `FATAL: role "admin01" does not exist`. Le compte administrateur de PostgreSQL s'appelle `postgres`, et `sudo -u postgres` lance la commande sous ce compte.

Vérifier que le schéma et les rôles existent :

```bash
sudo -u postgres psql -d meteo -c "\dt meteo.*"
sudo -u postgres psql -d meteo -c "\du"
```

La première commande liste les tables `instance`, `mesure`, `processus`, `indicateur`, `seuil` et `parametre`. La seconde montre les rôles `scrutateur` et `grafana_ro`.

### 1.3 Autoriser le bastion à se connecter (sur pg01)

Par défaut PostgreSQL n'écoute que sur lui-même. Les commandes ci-dessous supposent l'organisation Debian/Ubuntu (`/etc/postgresql/<version>/main/`) :

```bash
ls /etc/postgresql
```

Cette commande affiche le numéro de version (par exemple `16`). Si ce n'est pas `16`, remplacer le nombre dans les trois commandes suivantes.

```bash
echo "listen_addresses = '*'" | sudo tee /etc/postgresql/16/main/conf.d/meteo.conf
echo "host meteo scrutateur 192.168.50.10/32 scram-sha-256" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
echo "host meteo grafana_ro 192.168.50.10/32 scram-sha-256" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
sudo systemctl restart postgresql
sudo ss -tlnp | grep 5432
```

La dernière commande doit montrer une ligne avec `0.0.0.0:5432` ou `*:5432`. Ubuntu Server n'active pas de pare-feu par défaut : aucune règle à ajouter sur pg01.

### 1.4 Vérifier que le bastion atteint le stockage (sur le bastion)

Se connecter : `ssh admin01@192.168.50.10`. Puis :

```bash
sudo apt update
sudo apt install -y postgresql-client
psql -h pg01 -U scrutateur -d meteo -c "SELECT nom, actif FROM meteo.instance"
```

`psql` demande le mot de passe : taper `MOT_DE_PASSE_1`. Le résultat est vide tant qu'aucune instance n'est déclarée (2.5) ; une erreur de connexion se traite avec le dépannage en fin de document. Ici `-h` désigne la machine PostgreSQL, `-U` le rôle et `-d` la base.

## 2. Instance PostgreSQL à surveiller (pg02)

### 2.1 Installer PostgreSQL (sur pg02)

Se connecter : `ssh admin01@192.168.50.21`. Puis :

```bash
sudo apt update
sudo apt install -y postgresql
psql --version
```

Toute version de PostgreSQL ≥ 10 convient pour la requête de supervision (`pg_monitor`, `pg_blocking_pids`). Si pg02 est une instance existante, passer directement à 2.2.

### 2.2 Créer le login de supervision (sur pg02, dans la console PostgreSQL)

```bash
sudo -u postgres psql
```

L'invite devient `postgres=#`. Taper :

```sql
CREATE ROLE scrutateur LOGIN PASSWORD 'MOT_DE_PASSE_CIBLE';
GRANT pg_monitor TO scrutateur;
```

Les réponses sont `CREATE ROLE` et `GRANT ROLE`. Quitter avec `\q`.

- `pg_monitor` est indispensable : sans lui PostgreSQL **masque** l'état, la requête et le début de transaction des sessions des autres utilisateurs, et le tableau serait faussement vide. Le scrutateur le contrôle avant chaque relevé et, s'il manque, produit l'erreur `le login 'scrutateur' doit etre membre de pg_monitor` (instance « inconnu », jamais un faux soleil).
- Ce login ne reçoit **aucun** autre droit : il ne lit aucune donnée applicative, il ne lit jamais le texte des requêtes (seul le premier mot est conservé) et sa connexion est ouverte en lecture seule.
- Pour que le login n'ait pas d'autre portée : `ALTER ROLE scrutateur NOSUPERUSER NOCREATEDB NOCREATEROLE;` (valeurs par défaut de toute façon).

### 2.3 Autoriser le bastion à se connecter (sur pg02)

```bash
ls /etc/postgresql
```

Affiche le numéro de version (par exemple `16`) ; s'il diffère, le remplacer dans les commandes suivantes.

```bash
echo "listen_addresses = '*'" | sudo tee /etc/postgresql/16/main/conf.d/meteo.conf
echo "host all scrutateur 192.168.50.10/32 scram-sha-256" | sudo tee -a /etc/postgresql/16/main/pg_hba.conf
sudo systemctl restart postgresql
sudo ss -tlnp | grep 5432
```

La dernière commande doit montrer `0.0.0.0:5432` ou `*:5432`. La base de connexion du scrutateur (colonne `base` de `meteo.instance`, `postgres` par défaut) n'a pas d'importance pour la requête : `pg_stat_activity` montre toutes les bases de l'instance. Sur une instance existante, ajouter la même ligne `pg_hba.conf` (adresse du bastion), puis `sudo systemctl reload postgresql`.

### 2.4 Vérifier depuis le bastion (sur le bastion)

```bash
sudo apt install -y postgresql-client
psql -h 192.168.50.21 -U scrutateur -d postgres -c "SELECT pg_has_role(current_user, 'pg_monitor', 'USAGE')"
```

`psql` demande `MOT_DE_PASSE_CIBLE`. Le résultat doit être `t`. Puis essayer la requête réelle du scrutateur :

```bash
psql -h 192.168.50.21 -U scrutateur -d postgres -f ~/RT_Meteo_PG/sql/cible/supervision.sql
```

(le dépôt est cloné en 3.1). Le tableau peut être vide si personne n'exécute de requête.

### 2.5 Déclarer l'instance dans le stockage (sur pg01)

```bash
sudo -u postgres psql -d meteo
```

```sql
INSERT INTO meteo.instance (nom, login, password, host, port, base)
VALUES ('pg02', 'scrutateur', 'MOT_DE_PASSE_CIBLE', '192.168.50.21', 5432, 'postgres');
SELECT nom, host, port, base, actif FROM meteo.instance;
```

La console répond `INSERT 0 1`. Autres opérations dans la même console :

```sql
-- Changer un mot de passe :
UPDATE meteo.instance SET password = 'NOUVEAU_MOT_DE_PASSE' WHERE nom = 'pg02';
-- Retirer une instance de la surveillance (ou la réactiver avec true) :
UPDATE meteo.instance SET actif = false WHERE nom = 'pg02';
```

- Si le mot de passe contient une apostrophe, la doubler (`''`).
- `nom` est le nom affiché et doit être écrit **exactement** pareil (majuscules comprises) dans `--tester` (3.4).
- Le scrutateur relit cette table à chaque cycle : aucune relance n'est nécessaire.
- Le mot de passe est stocké en clair : n'accorder aucun autre droit sur cette table (voir `sql/stockage/002_roles.sql`).

### 2.6 Fabriquer des situations à observer (sur pg02, deux sessions)

Pour obtenir des captures d'écran des différents états. Ouvrir **deux** connexions SSH à pg02 et, dans chacune, `sudo -u postgres psql`. Préparation (une fois) :

```sql
CREATE TABLE IF NOT EXISTS public.demo(id int PRIMARY KEY, v text);
INSERT INTO public.demo VALUES (1, 'a') ON CONFLICT DO NOTHING;
```

| Situation | Session A | Session B |
|---|---|---|
| Requête longue | `SELECT pg_sleep(150);` | — |
| Transaction ouverte (inactive) | `BEGIN; SELECT 1;` (puis ne rien faire ; `COMMIT;` pour finir) | — |
| Blocage + bloqueur | `BEGIN; UPDATE public.demo SET v='x' WHERE id=1;` (puis ne rien faire) | `UPDATE public.demo SET v='y' WHERE id=1;` (attend) |

Pour terminer : `COMMIT;` dans A (débloque B), `Ctrl+C` pour interrompre `pg_sleep`. Les seuils par défaut (nuage / orage) sont : blocage max 30 s / 120 s, requête max 60 s / 300 s, transaction max 300 s / 900 s ; attendre donc 1 à 5 minutes pour voir le changement d'icône.

## 3. Scrutateur sur le bastion

### 3.1 Récupérer le code sur le bastion (sur le bastion)

Se connecter : `ssh admin01@192.168.50.10`. Puis :

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/serentz/RT_Meteo_PG.git
cd RT_Meteo_PG
```

Si le dépôt est privé ou si le bastion n'a pas d'accès à Internet, copier le dossier depuis Windows. Dans PowerShell (sur Windows) :

```powershell
scp -r I:\POC\RT_Meteo_PG\scrutateur I:\POC\RT_Meteo_PG\sql admin01@192.168.50.10:~/
```

Les commandes suivantes se tapent dans le dossier qui contient `scrutateur/`.

### 3.2 Installer (sur le bastion)

```bash
sudo apt install -y python3-venv
sudo useradd --system --home-dir /opt/scrutateur --shell /usr/sbin/nologin scrutateur
sudo mkdir -p /opt/scrutateur/app /etc/scrutateur
sudo cp -r scrutateur /opt/scrutateur/app/
sudo python3 -m venv /opt/scrutateur/venv
sudo /opt/scrutateur/venv/bin/pip install -r /opt/scrutateur/app/scrutateur/requirements.txt
sudo install -m 0640 -o root -g scrutateur scrutateur/deploy/scrutateur.env.example /etc/scrutateur/scrutateur.env
sudo install -m 0644 scrutateur/deploy/scrutateur.service /etc/systemd/system/scrutateur.service
sudo systemctl daemon-reload
```

Le seul module Python externe est `psycopg` (version « binary », qui embarque `libpq`) : ni ODBC ni FreeTDS.

### 3.3 Renseigner le mot de passe du stockage (sur le bastion)

```bash
sudo nano /etc/scrutateur/scrutateur.env
```

Le fichier contient une ligne `SCRUTATEUR_STOCKAGE_DSN=...`. Remplacer `CHANGER_MOI` par `MOT_DE_PASSE_1`, pour obtenir :

```
SCRUTATEUR_STOCKAGE_DSN=postgresql://scrutateur:MOT_DE_PASSE_1@pg01:5432/meteo
```

Enregistrer avec `Ctrl+O` puis `Entrée`, quitter avec `Ctrl+X`. Si le mot de passe contient `@ : / ? # %`, encoder ces caractères en pourcentage dans l'URL (`@` devient `%40`).

### 3.4 Essayer, puis démarrer (sur le bastion)

Ces commandes lancent le script sous le compte de service `scrutateur`, avec les variables du fichier ci-dessus.

Essai d'une instance, sans rien écrire dans le stockage (remplacer `pg02` par le nom déclaré en 2.5, majuscules comprises) :

```bash
sudo -u scrutateur bash -c 'set -a; . /etc/scrutateur/scrutateur.env; set +a; cd /opt/scrutateur/app && /opt/scrutateur/venv/bin/python -m scrutateur --tester pg02'
```

Le script lit l'instance dans `meteo.instance` (le stockage doit donc être joignable et l'instance déclarée), interroge pg02 et affiche en JSON les indicateurs (`nb_bloques`, `blocage_max_s`, `requete_max_s`, `transaction_max_s`...) et le tableau des processus lus (`details`). Si l'instance est absente ou inactive, il liste celles qu'il connaît ; si pg02 ne répond pas, il affiche une ligne d'erreur.

Un cycle complet (écrit dans le stockage), puis démarrage du service :

```bash
sudo -u scrutateur bash -c 'set -a; . /etc/scrutateur/scrutateur.env; set +a; cd /opt/scrutateur/app && /opt/scrutateur/venv/bin/python -m scrutateur --une-fois -v'
sudo systemctl enable --now scrutateur
sudo journalctl -u scrutateur -f
```

`journalctl -f` suit le journal du service ; `Ctrl+C` arrête le suivi, pas le service.

### 3.5 Lire le résultat (sur pg01)

```bash
sudo -u postgres psql -d meteo -c "SELECT * FROM meteo.etat_instance"
sudo -u postgres psql -d meteo -c "SELECT * FROM meteo.etat_indicateur WHERE instance = 'pg02'"
```

## 4. Grafana sur le bastion (écrans soleil / nuage / orage)

Tout se tape **sur le bastion** (`ssh admin01@192.168.50.10`), à partir du dossier cloné en 3.1 (`~/RT_Meteo_PG`, à mettre à jour avec `git pull`). Non testé dans ce projet au moment de l'écriture (la même configuration a été validée dans RT_Meteo_ASE) : à valider et à corriger ici si besoin.

### 4.1 Installer Grafana

```bash
sudo apt-get install -y apt-transport-https wget gpg
sudo mkdir -p /etc/apt/keyrings
wget -q -O - https://apt.grafana.com/gpg.key | gpg --dearmor | sudo tee /etc/apt/keyrings/grafana.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/grafana.gpg] https://apt.grafana.com stable main" | sudo tee /etc/apt/sources.list.d/grafana.list
sudo apt-get update && sudo apt-get install -y grafana
grafana-server --version
```

Les tableaux de bord demandent Grafana 10.4 ou plus récent (cellules « image » des tableaux, source `grafana-postgresql-datasource`).

La synthèse en tuiles (icône, nom dessous) utilise le greffon Grafana « Business Text » :

```bash
sudo grafana cli plugins install marcusolsson-dynamictext-panel
sudo systemctl restart grafana-server
```

Sans ce greffon, l'écran « Météo des instances PostgreSQL » affiche une erreur de panneau ; utiliser alors l'écran « (liste) », qui n'en a pas besoin. Le greffon 6.x demande Grafana 11 ou 12, le 5.x Grafana 10 ou 11 (le dépôt du greffon est archivé depuis septembre 2025).

### 4.2 Déployer la configuration du dépôt

```bash
cd ~/RT_Meteo_PG
sudo mkdir -p /var/lib/grafana/dashboards/meteo /usr/share/grafana/public/img/meteo \
  /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards
sudo cp grafana/dashboards/*.json /var/lib/grafana/dashboards/meteo/
sudo cp grafana/provisioning/datasources/meteo.yaml /etc/grafana/provisioning/datasources/
sudo cp grafana/provisioning/dashboards/meteo.yaml /etc/grafana/provisioning/dashboards/
sudo cp images/iconnes/*.png /usr/share/grafana/public/img/meteo/
```

Les icônes sont servies par Grafana sous `/public/img/meteo/` (à recopier après une mise à jour du paquet Grafana).

### 4.3 Donner à Grafana le mot de passe du rôle `grafana_ro`

Le mot de passe n'est pas dans Git : le fichier de la source de données le lit dans l'environnement du service.

```bash
echo 'METEO_GRAFANA_PWD=MOT_DE_PASSE_2' | sudo tee -a /etc/default/grafana-server > /dev/null
sudo systemctl enable --now grafana-server
systemctl status grafana-server
```

`MOT_DE_PASSE_2` est celui donné à `002_roles.sql` (voir « où taper quoi »). Éviter les guillemets et les espaces dans ce mot de passe.

### 4.4 Ouvrir les écrans

Depuis le navigateur du PC Windows : `http://192.168.50.10:3000`. Premier accès : utilisateur `admin`, mot de passe `admin`, que Grafana demande de changer. Menu *Dashboards* :

- **Météo des instances PostgreSQL** : une tuile par instance avec son icône (soleil, nuage, orage, lune) et son nom en dessous, bordure de la couleur de l'état, âge du relevé. Un clic ouvre le détail. Rafraîchi toutes les 30 s.
- **Météo des instances PostgreSQL (liste)** : la même synthèse en tableau, sans greffon (secours).
- **Détail d'une instance PostgreSQL** : choisir l'instance en haut ; état, un indicateur par ligne (valeur, unité, seuils, icône) le tableau des processus du dernier relevé (requêtes en cours, bloqués avec leur bloqueur, base, attente) et celui des transactions ouvertes, de la plus longue à la plus courte.

Si les tableaux sont vides ou en erreur : *Connections → Data sources → meteo → Save & test*. Une erreur d'authentification vient de `METEO_GRAFANA_PWD` ou de la ligne `grafana_ro` dans `pg_hba.conf` (1.3) ; `sudo journalctl -u grafana-server -n 30 --no-pager` donne le détail.

## 5. Passage à l'échelle (100 ou 200 instances)

**Un scrutateur gère déjà plusieurs instances** : chaque relevé tourne dans son propre thread (`SCRUTATEUR_MAX_PARALLELE`, 16 par défaut). La limite est le nombre de « secondes-thread » par minute : `threads nécessaires ≈ nombre d'instances × durée d'un relevé ÷ 60`, auxquels s'ajoutent les instances en panne (jusqu'à 10 s de délai de connexion chacune). On dimensionne sur le pire cas.

### 5.1 Mesurer la durée d'un relevé (sur pg01)

```bash
sudo -u postgres psql -d meteo
```

```sql
SELECT i.nom, count(*) AS releves, round(avg(m.duree_ms)) AS moy_ms,
       percentile_disc(0.95) WITHIN GROUP (ORDER BY m.duree_ms) AS p95_ms,
       max(m.duree_ms) AS max_ms
FROM meteo.mesure m JOIN meteo.instance i USING (instance_id)
WHERE m.collecte_le > now() - interval '1 hour' AND m.statut = 'ok'
GROUP BY i.nom ORDER BY p95_ms DESC;
```

Exemple : 200 instances à 0,5 s (p95) = 100 s-thread par minute, soit environ 2 threads occupés ; 20 instances en panne à 10 s = 200 s-thread, soit environ 3,5 threads de plus. 16 threads suffisent largement ; au-delà, monter `SCRUTATEUR_MAX_PARALLELE` (32 ou 64, ce sont des threads qui attendent le réseau). Vérifier alors `max_connections` sur pg01 et sur les instances.

### 5.2 Étalement des relevés (activé par défaut)

Au lieu de lancer les 200 relevés à la même seconde, le scrutateur répartit régulièrement leurs départs sur `SCRUTATEUR_ETALEMENT_S` secondes (20 par défaut, 0 pour désactiver, au plus la moitié de l'intervalle). Cela évite la rafale de connexions vers pg01 et vers les instances, et réduit le nombre de threads nécessaires. La cadence de chaque instance reste d'un relevé par minute. En mode `--une-fois`, il n'y a pas d'étalement.

### 5.3 Plusieurs scrutateurs sur le bastion (partition)

Le scrutateur `i/N` (`i` de 0 à N-1) ne relève que les instances dont `instance_id % N = i` : chaque instance est relevée par un seul scrutateur, aucune n'est oubliée, et une instance ajoutée est attribuée toute seule. Exemple avec deux scrutateurs (sur le bastion) :

```bash
sudo install -m 0644 ~/RT_Meteo_PG/scrutateur/deploy/scrutateur@.service /etc/systemd/system/scrutateur@.service
echo 'SCRUTATEUR_PARTITION=0/2' | sudo tee /etc/scrutateur/partition-0.env
echo 'SCRUTATEUR_PARTITION=1/2' | sudo tee /etc/scrutateur/partition-1.env
sudo chown root:scrutateur /etc/scrutateur/partition-*.env
sudo systemctl daemon-reload
sudo systemctl disable --now scrutateur
sudo systemctl enable --now scrutateur@0 scrutateur@1
sudo journalctl -u 'scrutateur@*' -f
```

Chaque journal indique `Cycle (partition i/N) : k instance(s) lancée(s) sur n`. Si un scrutateur s'arrête, ses instances passent en « inconnu » au bout de 180 s (jamais de faux soleil) : le contrôle se fait sur `meteo.etat_instance`. Pour changer N, modifier **tous** les fichiers `partition-*.env` puis redémarrer tous les services (sinon des instances seraient relevées deux fois ou jamais).

### 5.4 Signal de saturation

Si plus de relevés sont en cours qu'il n'y a de threads, le journal affiche `N releves en cours pour M thread(s) : des releves attendent un thread` : augmenter `SCRUTATEUR_MAX_PARALLELE` ou ajouter une partition. Un relevé en retard dont le suivant arrive est sauté (`releve precedent toujours en cours`).

## Réglages

Variables de `/etc/scrutateur/scrutateur.env` (valeurs par défaut entre parenthèses) : `SCRUTATEUR_INTERVALLE_S` (60), `SCRUTATEUR_MAX_PARALLELE` (16), `SCRUTATEUR_CIBLE_CONNEXION_TIMEOUT_S` (10), `SCRUTATEUR_CIBLE_REQUETE_TIMEOUT_S` (15), `SCRUTATEUR_CIBLE_SSLMODE` (`prefer` ; `disable`, `allow`, `prefer`, `require`, `verify-ca`, `verify-full`), `SCRUTATEUR_ETALEMENT_S` (20), `SCRUTATEUR_PARTITION` (vide = un seul scrutateur, sinon `i/N`). Après modification : `sudo systemctl restart scrutateur`. Le scrutateur avertit au démarrage si un relevé peut dépasser l'intervalle.

## Dépannage

| Message ou symptôme | Où | Piste |
|---|---|---|
| `psql: FATAL: role "admin01" does not exist` | pg01, pg02 | `psql` a été lancé sans `sudo -u postgres` : utiliser `sudo -u postgres psql`. |
| `Connection refused` (port 5432) | bastion | `listen_addresses` non appliqué ou PostgreSQL non redémarré : refaire 1.3 (pg01) ou 2.3 (pg02) et vérifier avec `sudo ss -tlnp \| grep 5432`. |
| `no pg_hba.conf entry for host` | bastion | Ligne `host ... 192.168.50.10/32 ...` absente de `pg_hba.conf` sur la machine visée : refaire 1.3 ou 2.3. |
| `password authentication failed for user "scrutateur"` | bastion | Sur pg01 : `MOT_DE_PASSE_1` différent de celui donné à `002_roles.sql`, ou caractère spécial non encodé dans `scrutateur.env`. Pour une instance surveillée : `MOT_DE_PASSE_CIBLE` différent de celui de `meteo.instance` (`UPDATE` de 2.5). |
| `Connexion a PostgreSQL impossible (OperationalError)` ou `failed to resolve host 'xxx@pg01'` | bastion | Le mot de passe de `SCRUTATEUR_STOCKAGE_DSN` contient un caractère spécial (`@`, `:`, `/`, `#`, `%`, `?`) : dans l'URL il doit être encodé (`@` devient `%40`). Obtenir la forme encodée : `python3 -c "import urllib.parse,getpass;print(urllib.parse.quote(getpass.getpass(),safe=''))"`. Le plus simple : un mot de passe sans caractère spécial. |
| `could not translate host name "pg01"` | bastion | Résolution de nom : remplacer `pg01` par `192.168.50.11` dans `scrutateur.env` (ou le `host` par l'IP dans `meteo.instance`). |
| `DroitsInsuffisants` : « doit etre membre de pg_monitor » | bastion (journal) | Faire `GRANT pg_monitor TO scrutateur;` sur l'instance surveillée (2.2). |
| `canceling statement due to statement timeout` | bastion (journal) | Instance surchargée : augmenter `SCRUTATEUR_CIBLE_REQUETE_TIMEOUT_S`. |
| `connection to server ... SSL ...` | bastion | Régler `SCRUTATEUR_CIBLE_SSLMODE` (`disable` si le serveur n'a pas de TLS et refuse la négociation). |
| `ModuleNotFoundError: No module named 'psycopg'` | bastion | `pip install` de 3.2 non exécuté dans le venv `/opt/scrutateur/venv`. |
| Instance en « inconnu » alors qu'elle répond | pg01 | Relevé périmé (plus de 180 s) : lire `sudo journalctl -u scrutateur` sur le bastion et la colonne `erreur` de `meteo.etat_instance`. |
| Le tableau est vide alors qu'il y a des sessions | bastion | Login non membre de `pg_monitor` (contrôle en 2.4) : les sessions des autres utilisateurs sont masquées par PostgreSQL. |

## Tests

Sans dépendance externe, depuis la racine du dépôt (sur une machine Linux avec Python 3) :

```bash
python3 -m unittest discover -s tests -t . -v
```

Test du schéma de stockage, sur une base **jetable** (tout est annulé à la fin du test). D'abord, dans PowerShell sur Windows :

```powershell
scp -r I:\POC\RT_Meteo_PG\tests admin01@192.168.50.11:/tmp/
```

Puis sur pg01 (les scripts `sql` ont été envoyés en 1.1) :

```bash
sudo -u postgres createdb meteo_test
sudo -u postgres psql -d meteo_test -v ON_ERROR_STOP=1 -f /tmp/sql/stockage/001_schema.sql
sudo -u postgres psql -d meteo_test -v ON_ERROR_STOP=1 -v pwd_scrutateur='x' -v pwd_grafana='y' -f /tmp/sql/stockage/002_roles.sql
sudo -u postgres psql -d meteo_test -v ON_ERROR_STOP=1 -f /tmp/tests/stockage/test_schema.sql
sudo -u postgres dropdb meteo_test
```

Le test affiche `OK : tous les controles du schema sont passes` avant la dernière commande, qui supprime la base jetable. Les rôles `scrutateur` et `grafana_ro` sont créés au niveau de l'instance : `002_roles.sql` peut être rejoué sans dommage.

## Validation

Réalisé dans l'environnement de préparation (Linux, PostgreSQL 16) :

- 60 tests Python (calculs sur le tableau, lecture d'une instance avec un faux pilote `psycopg`, contrôle de `pg_monitor`, parallélisme, panne d'une instance, relecture de `meteo.instance`, panne du stockage, mot de passe masqué, cohérence entre la requête, le fichier SQL et le schéma) ;
- schéma, vues, fonction d'écriture et droits des rôles testés sur un vrai PostgreSQL 16 (`tests/stockage/test_schema.sql`) ;
- requête de `sql/cible/supervision.sql` exécutée sur un vrai PostgreSQL 16 avec bloqueur, session bloquée, requête longue, transaction ouverte inactive et login sans `pg_monitor`.

**Non réalisé, à valider sur les VM** : connexion réelle du scrutateur avec `psycopg` (le module n'était pas installable dans l'environnement de préparation), service systemd, création des VM par le script PowerShell (pg02), Grafana (tuiles, liste, détail, panneau des transactions), scénarios de 2.6 avec les seuils (provisoires), et `blocage_s` (approximation : durée de l'instruction bloquée, PostgreSQL n'indiquant pas le début de l'attente).
