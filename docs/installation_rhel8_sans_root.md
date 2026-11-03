# Installation sur RHEL 8.10 avec le Python 3.6.8 du système, sans droits root

Cette fiche installe le scrutateur sur un bastion **RHEL 8.10** en utilisant le `python3` du système (**3.6.8**), sans rien installer au niveau du serveur : ni `dnf`, ni `sudo`, ni modification du Python utilisé par Ansible et les jobs. Tout se trouve dans le dossier personnel du compte qui exécute le scrutateur (`~/scrutateur`).

Le code a été adapté pour cela. Les tests (74 pour ce projet) passent sous un **vrai Python 3.6.8** (compilé depuis les sources) et sous Python 3.13. **Non testé** : la connexion réelle sous Python 3.6 (pilote `psycopg` 3.0, dernière série compatible avec la 3.6) et le lancement sous RHEL ; à corriger ici au premier essai si besoin. Python 3.6 n'est plus maintenu par la communauté Python (seul Red Hat corrige les failles du paquet RHEL) : à garder pour un POC ou tant qu'une version plus récente n'est pas disponible. La fiche [installation_rhel8.md](installation_rhel8.md) décrit l'autre voie, avec un Python récent installé à côté (elle demande `sudo`).

## 1. Vérifications préalables

Tout se tape sur le bastion, **sous le compte qui exécutera le scrutateur**. Si ce compte est `sybase` et que l'on n'a pas son mot de passe, demander à l'administrateur d'ouvrir l'accès (`sudo -iu sybase`, clé SSH) ou exécuter le scrutateur sous un compte personnel : la suite est identique.

```bash
whoami
echo "$HOME"
cat /etc/redhat-release
python3 --version
python3 -m venv --help | head -1
```

`python3 --version` doit afficher `Python 3.6.8` (ou plus récent : la fiche convient aussi). La dernière commande doit afficher un `usage: venv`.

Contrôler que le réseau est ouvert, sans outil installé :

```bash
timeout 3 bash -c '</dev/tcp/pg01/5432' && echo "pg01:5432 ouvert" || echo "pg01:5432 FERME"
curl -sI https://pypi.org/simple/ | head -1
```

- `pg01:5432` doit être ouvert (adapter le nom si le stockage porte un autre nom). Sinon, un pare-feu ou `pg_hba.conf` bloque : voir les sections 1.3 et 1.5 de [scrutateur.md](scrutateur.md).
- La seconde commande doit afficher `HTTP/… 200`. Si PyPI est inaccessible (proxy ou réseau coupé), utiliser l'installation depuis des fichiers copiés à la main (étape 3.3).

## 2. Récupérer le code

```bash
cd ~
git clone https://github.com/serentz/RT_Meteo_PG.git
cd RT_Meteo_PG
```

Sans `git` ou sans accès à GitHub, copier le dossier depuis Windows (PowerShell) puis, sur le bastion, se placer dans le dossier qui contient `scrutateur/` :

```powershell
scp -r I:\POC\RT_Meteo_PG\scrutateur I:\POC\RT_Meteo_PG\sql COMPTE@ADRESSE_DU_BASTION:~/RT_Meteo_PG/
```

## 2bis. Stockage sur un serveur PostgreSQL existant (accès par `psql` et `~/.pgpass`)

Cette section remplace les sections 1.1 à 1.3 de [scrutateur.md](scrutateur.md) quand la base de stockage (`meteo`) est créée sur un **serveur PostgreSQL déjà en place** (version 15 ou plus), joint depuis le bastion avec `psql`. Aucun nom de serveur n'est écrit dans ce dépôt : remplacer `SERVEUR_PG` par le nom complet du serveur.

**Mots de passe : `~/.pgpass`.** `psql` et `psycopg` (donc le scrutateur) lisent `~/.pgpass` quand aucun mot de passe n'est donné. Une ligne par rôle, au format `serveur:port:base:rôle:mot_de_passe` (fichier en mode `0600`, sinon il est ignoré ; échapper `\` et `:` dans le mot de passe par un `\` devant). Pour ne pas laisser le mot de passe dans l'historique du shell :

```bash
read -rsp "Mot de passe du rôle scrutateur : " P; echo
printf '%s\n' "SERVEUR_PG:5432:meteo:scrutateur:$P" >> ~/.pgpass
unset P
chmod 600 ~/.pgpass
```

Avec cela, la ligne du fichier `scrutateur.env` (étape 4) ne contient **aucun mot de passe** :

```
SCRUTATEUR_STOCKAGE_DSN=postgresql://scrutateur@SERVEUR_PG:5432/meteo
```

**Créer la base et les rôles** (compte administrateur du serveur, `postgres` ici, dont le mot de passe est dans `~/.pgpass`). `/usr/pgsql-17/bin` n'est pas dans le `PATH` par défaut : utiliser le chemin complet, ou l'ajouter dans la session.

```bash
export PATH="$PATH:/usr/pgsql-17/bin"
cd ~/RT_Meteo_PG
psql -h SERVEUR_PG -U postgres -d postgres -c "SELECT version()"
psql -h SERVEUR_PG -U postgres -d postgres -c "CREATE DATABASE meteo"
psql -h SERVEUR_PG -U postgres -d meteo -v ON_ERROR_STOP=1 -f sql/stockage/001_schema.sql
psql -h SERVEUR_PG -U postgres -d meteo -v ON_ERROR_STOP=1 \
  -v pwd_scrutateur='MOT_DE_PASSE_1' -v pwd_grafana='MOT_DE_PASSE_2' -f sql/stockage/002_roles.sql
psql -h SERVEUR_PG -U postgres -d meteo -c "\dt meteo.*"
```

- Les rôles `scrutateur` et `grafana_ro` sont créés **au niveau du serveur** (partagés entre toutes ses bases) : s'assurer auprès de l'administrateur du serveur qu'ils n'existent pas déjà et qu'il accepte la création d'une base `meteo`.
- Le serveur doit autoriser ces deux rôles sur la base `meteo`, depuis l'adresse du bastion (et de Grafana), dans son `pg_hba.conf` : `host meteo scrutateur ADRESSE_BASTION/32 scram-sha-256` et la ligne équivalente pour `grafana_ro`, puis rechargement (`SELECT pg_reload_conf()`). Sans accès à ce fichier, le demander à l'administrateur.
- Ajouter ensuite les lignes de `~/.pgpass` des deux rôles, puis contrôler : `psql -h SERVEUR_PG -U scrutateur -d meteo -c "SELECT nom, actif FROM meteo.instance"` doit répondre sans demander de mot de passe.
- Déclarer les instances surveillées avec `INSERT INTO meteo.instance …` (voir la section 1.4 de [scrutateur.md](scrutateur.md)), en lançant `psql -h SERVEUR_PG -U postgres -d meteo` au lieu de `sudo -u postgres psql -d meteo`.

## 3. Environnement Python (dans le dossier personnel)

### 3.1 Dossiers et copie du code

```bash
mkdir -p ~/scrutateur/app
cp -r scrutateur ~/scrutateur/app/
```

### 3.2 Environnement virtuel et modules

```bash
python3 -m venv ~/scrutateur/venv
~/scrutateur/venv/bin/pip install --upgrade "pip<22"
~/scrutateur/venv/bin/pip install -r ~/scrutateur/app/scrutateur/requirements.txt
~/scrutateur/venv/bin/pip list
```

- Le `pip` livré avec Python 3.6 (9.0) est trop ancien pour installer les paquets binaires modernes : la deuxième commande installe `pip` 21.3 dans le venv, le dernier compatible avec la 3.6. Rien n'est modifié hors de `~/scrutateur`.
- `requirements.txt` choisit seul les bonnes versions selon Python (`psycopg` 3.0 et le module `dataclasses` pour la 3.6).
- Si `python3 -m venv` répond `ensurepip is not available`, créer le venv sans `pip` puis installer `pip` : `python3 -m venv --without-pip ~/scrutateur/venv`, `curl -fsSL https://bootstrap.pypa.io/pip/3.6/get-pip.py -o ~/get-pip.py`, `~/scrutateur/venv/bin/python ~/get-pip.py "pip<22"`.

### 3.3 Sans accès à PyPI : installer depuis des fichiers copiés à la main

Sur un poste connecté, dans un dossier vide :

```bash
pip download -d wheels --only-binary=:all: --platform manylinux2014_x86_64 \
  --python-version 3.6 --implementation cp --abi cp36m "psycopg[binary]>=3.0.15,<3.1" "dataclasses>=0.8,<1"
```

Copier le dossier `wheels` sur le bastion (`scp -r wheels COMPTE@ADRESSE_DU_BASTION:~/`), puis :

```bash
~/scrutateur/venv/bin/pip install --no-index --find-links ~/wheels "psycopg[binary]>=3.0.15,<3.1" "dataclasses>=0.8,<1"
```

(Le `pip` du venv doit déjà être à jour : copier aussi `pip-21.3.1-py3-none-any.whl` obtenu par `pip download "pip<22"`, et l'installer d'abord avec `~/scrutateur/venv/bin/pip install ~/wheels/pip-21.3.1-py3-none-any.whl`.)

## 4. Configuration

```bash
cp ~/RT_Meteo_PG/scrutateur/deploy/scrutateur.env.example ~/scrutateur/scrutateur.env
chmod 600 ~/scrutateur/scrutateur.env
nano ~/scrutateur/scrutateur.env
```

Remplacer `CHANGER_MOI` (ou, avec un `~/.pgpass`, le retirer : voir la section 2bis) dans la ligne `SCRUTATEUR_STOCKAGE_DSN=postgresql://scrutateur:CHANGER_MOI@pg01:5432/meteo` par le mot de passe du rôle `scrutateur` de pg01. Si le mot de passe contient `@ : / ? # %`, l'encoder dans l'URL (`@` devient `%40`) :

```bash
python3 -c "import urllib.parse,getpass;print(urllib.parse.quote(getpass.getpass(),safe=''))"
```

Laisser la ligne `PYTHONIOENCODING=utf-8` : sous Python 3.6, sans elle, un message accentué (par exemple une erreur en français renvoyée par une instance) provoque une erreur d'affichage dans le journal.

## 5. Essayer

Remplacer `pg02` par le nom déclaré dans `meteo.instance` (majuscules comprises) :

```bash
cd ~/scrutateur/app
set -a; . ~/scrutateur/scrutateur.env; set +a
~/scrutateur/venv/bin/python -m scrutateur --tester pg02
~/scrutateur/venv/bin/python -m scrutateur --une-fois -v
```

La première commande affiche en JSON les indicateurs lus sur l'instance, sans rien écrire. La seconde fait un cycle complet et écrit dans le stockage. Vérifier sur pg01 : `sudo -u postgres psql -d meteo -c "SELECT * FROM meteo.etat_instance"` (ou `psql` depuis un compte autorisé).

## 6. Le faire tourner en permanence, sans root

Choisir **une** des deux méthodes. Le scrutateur se relance lui-même à chaque cycle d'une minute, il n'a besoin que d'un processus qui reste en vie.

### 6.1 Service systemd « utilisateur » (préférable, si `enable-linger` est accepté)

```bash
loginctl enable-linger "$USER"
loginctl show-user "$USER" -p Linger
```

La seconde commande doit afficher `Linger=yes`. Si la première répond `Access denied`, passer à la méthode 6.2. Créer le service :

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/scrutateur.service <<'EOT'
[Unit]
Description=Scrutateur RT_Meteo_PG
After=network-online.target

[Service]
Type=simple
EnvironmentFile=%h/scrutateur/scrutateur.env
WorkingDirectory=%h/scrutateur/app
ExecStart=%h/scrutateur/venv/bin/python -m scrutateur
Restart=on-failure
RestartSec=10
TimeoutStopSec=60

[Install]
WantedBy=default.target
EOT
systemctl --user daemon-reload
systemctl --user enable --now scrutateur
systemctl --user status scrutateur --no-pager
```

Le service démarre au redémarrage du serveur et survit à la fermeture de la session SSH grâce à `enable-linger`. Journal : `journalctl --user -u scrutateur -n 20 --no-pager` (si le journal de l'utilisateur n'est pas lisible, `systemctl --user status scrutateur -l` affiche les dernières lignes). Arrêt : `systemctl --user stop scrutateur`.

Si `systemctl --user` répond `Failed to connect to bus`, ouvrir une nouvelle session SSH ou exporter `XDG_RUNTIME_DIR=/run/user/$(id -u)` avant la commande.

### 6.2 Cron et verrou (si `enable-linger` est refusé)

Un petit script lance le scrutateur s'il ne tourne pas déjà, et cron l'appelle chaque minute (le verrou `flock` empêche d'avoir deux scrutateurs) :

```bash
cat > ~/scrutateur/lancer.sh <<'EOT'
#!/bin/bash
# Lance le scrutateur s'il ne tourne pas deja (verrou flock). Appele chaque minute par cron.
cd "$HOME/scrutateur/app" || exit 1
set -a; . "$HOME/scrutateur/scrutateur.env"; set +a
exec flock -n "$HOME/scrutateur/scrutateur.lock" \
  "$HOME/scrutateur/venv/bin/python" -m scrutateur >> "$HOME/scrutateur/scrutateur.log" 2>&1
EOT
chmod 700 ~/scrutateur/lancer.sh
(crontab -l 2>/dev/null; echo "* * * * * $HOME/scrutateur/lancer.sh") | crontab -
crontab -l
```

Au bout d'une minute : `tail -3 ~/scrutateur/scrutateur.log` doit afficher `Cycle (partition 0/1) : N instance(s) lancee(s) sur N`. Le journal grossit d'environ 6 Mo par mois : le vider de temps en temps (`: > ~/scrutateur/scrutateur.log`).

Arrêt : retirer la ligne de cron (`crontab -e`), puis `pkill -u "$USER" -f "venv/bin/python -m scrutateur"`. Si `crontab` répond `You (COMPTE) are not allowed to use this program`, le compte est interdit dans `/etc/cron.allow` : demander à l'administrateur de l'ajouter.

## 7. Vérifier

- `ps -u "$USER" -o pid,etime,cmd | grep "[s]crutateur"` : un seul processus `python -m scrutateur`.
- Le journal (6.1 ou 6.2) montre `N instance(s) lancee(s) sur N`, sans `WARNING` ni `ERROR`.
- Sur pg01 : `meteo.etat_instance` affiche l'instance avec un âge de quelques secondes.
- `python3 --version` affiche toujours `Python 3.6.8` : rien n'a été modifié côté système.

## 8. Grafana

Grafana ne s'installe pas sans droits d'administration (paquet RPM, port 3000, service). Deux possibilités :
- utiliser un Grafana déjà installé (≥ 10.4) : ne reste qu'à ajouter la source de données et importer les tableaux de bord du dépôt (`grafana/provisioning` et `grafana/dashboards`, voir la section 4.2 de [scrutateur.md](scrutateur.md)) ;
- demander à un administrateur d'installer Grafana (commandes RHEL : section 6 de [installation_rhel8.md](installation_rhel8.md)).

## 9. Mettre à jour, désinstaller

**Mise à jour du scrutateur** : `cd ~/RT_Meteo_PG && git pull --ff-only`, puis `rm -rf ~/scrutateur/app/scrutateur && cp -r scrutateur ~/scrutateur/app/` et `~/scrutateur/venv/bin/pip install -r ~/scrutateur/app/scrutateur/requirements.txt`. Redémarrer : `systemctl --user restart scrutateur` (6.1), ou `pkill -u "$USER" -f "venv/bin/python -m scrutateur"` (6.2 : cron le relance dans la minute).

**Désinstallation** : arrêter le scrutateur (6.1 : `systemctl --user disable --now scrutateur` et `rm ~/.config/systemd/user/scrutateur.service` ; 6.2 : retirer la ligne de cron et `pkill`), puis `rm -rf ~/scrutateur`. Le Python du système n'est jamais concerné.

## 10. Dépannage

| Symptôme | Cause et correction |
|---|---|
| `pip install` : `Could not find a version that satisfies the requirement psycopg…` ou `No matching distribution` | `pip` trop ancien dans le venv (refaire l'étape 3.2) ou accès à PyPI bloqué (proxy : `pip --proxy http://PROXY:PORT install …` ; sinon étape 3.3). |
| `psycopg` ne s'installe qu'en compilant (`pg_config not found`, `gcc`) | Aucun paquet binaire trouvé pour cette plateforme. Sans root, la compilation est impossible : demander l'installation de `postgresql-devel`, `gcc` et `python3-devel`, ou utiliser la voie avec Python récent ([installation_rhel8.md](installation_rhel8.md)). |
| `ModuleNotFoundError: No module named 'dataclasses'` | Le venv a été installé sans `requirements.txt` ou avec un autre Python : refaire 3.2. |
| `SyntaxError` ou `TypeError: 'type' object is not subscriptable` au démarrage | Version du dépôt antérieure à l'adaptation pour Python 3.6 : `git pull --ff-only` puis recopier le code (étape 9). |
| `UnicodeEncodeError` dans le journal | La ligne `PYTHONIOENCODING=utf-8` manque dans `scrutateur.env` (étape 4). |
| `Connexion a PostgreSQL impossible` ou `failed to resolve host 'xxx@pg01'` | Mot de passe avec caractère spécial non encodé dans l'URL (étape 4), ou port 5432 fermé (étape 1). |
| `Failed to connect to bus` avec `systemctl --user` | Voir la fin de 6.1. |
