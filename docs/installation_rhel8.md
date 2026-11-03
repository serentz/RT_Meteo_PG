# Installation du bastion sous RHEL 8.10 (Python local, sans toucher au Python du système)

Cette fiche installe le scrutateur et Grafana sur un bastion **RHEL 8.10**. Elle remplace les étapes `apt` de [scrutateur.md](scrutateur.md) (sections 3 et 4) ; les sections 1 et 2 (PostgreSQL, instances à surveiller) ne changent pas. **Non testée sur RHEL** : le code, lui, est validé sur Ubuntu 24.04 (voir [captures.md](captures.md)). Corriger cette fiche au premier essai si une commande diffère.

> **Sans droits root** ou sans vouloir installer de Python : le scrutateur fonctionne avec le Python 3.6.8 du système, voir [installation_rhel8_sans_root.md](installation_rhel8_sans_root.md). Cette fiche-ci concerne l'installation d'un Python plus récent à côté.

## 1. Principe et garde-fous

Sous RHEL 8, `python3` est en version 3.6 et Ansible, `dnf` et les jobs du serveur en dépendent. Le scrutateur fonctionne aussi avec le Python 3.6.8 du système (voir la fiche sans root), mais un Python plus récent reste préférable (3.6 n'est plus maintenu par la communauté Python). On n'y touche donc pas : on installe un second Python, **local**, dans `/opt/python/3.11`, et le venv du scrutateur (`/opt/scrutateur/venv`) est construit avec lui. Le service systemd appelle `/opt/scrutateur/venv/bin/python` par son chemin complet : il ne dépend d'aucune variable `PATH` ni d'aucun lien dans `/usr/bin`.

| À faire | À ne pas faire |
|---|---|
| Installer Python dans `/opt/python/3.11` (`make altinstall`) | Remplacer `/usr/bin/python3` ou `/usr/libexec/platform-python` |
| Utiliser le chemin complet `/opt/python/3.11/bin/python3.11` | Ajouter `/opt/python/3.11/bin` au `PATH` global (`/etc/profile.d`, `/etc/environment`) ou créer un lien dans `/usr/bin` ou `/usr/local/bin` |
| Installer les modules Python **uniquement** dans le venv `/opt/scrutateur/venv` | `sudo pip install` hors d'un venv |
| Laisser `alternatives` tel quel | `alternatives --set python3 …`, `dnf module switch-to python36`, `dnf remove python3*` |

Comme le Python local n'est ni dans le `PATH` ni dans `/usr/bin`, ni Ansible ni les jobs existants ne peuvent le choisir par erreur.

## 2. Avant de commencer

Tout se tape **sur le bastion** (`ssh admin01@192.168.50.10`, adapter l'adresse). Le compte doit pouvoir utiliser `sudo`.

**2.1 Noter l'état du Python système** (pour prouver en fin d'installation qu'il n'a pas bougé) :

```bash
cat /etc/redhat-release
python3 --version
/usr/libexec/platform-python --version
alternatives --display python3 2>&1 | head -5
ls -l /usr/bin/python* /usr/libexec/platform-python* > ~/python_avant.txt
rpm -qa 'python3*' | sort >> ~/python_avant.txt
sha256sum /usr/libexec/platform-python3.6 >> ~/python_avant.txt
```

`cat /etc/redhat-release` doit afficher `Red Hat Enterprise Linux release 8.10`. Garder `~/python_avant.txt`.

**2.2 Vérifier les dépôts de paquets** (abonnement Red Hat ou Satellite) :

```bash
sudo dnf repolist
```

Les dépôts `BaseOS` et `AppStream` doivent apparaître. Si le serveur passe par un proxy, l'exporter pour `dnf` (`proxy=` dans `/etc/dnf/dnf.conf`) et pour `pip` (voir le dépannage).

**2.3 Choisir où le bastion trouve le code Python** : accès direct à `python.org` et à PyPI, ou accès interdit (voir 3.2 et 5.4 pour la copie à la main depuis un autre poste).

## 3. Python local dans /opt/python/3.11

Deux méthodes. La **3.1** est celle de cette fiche (version indépendante du système). La **3.5** (paquet `python3.11` du dépôt AppStream) est plus rapide mais installe `/usr/bin/python3.11` : à utiliser seulement si l'équipe qui gère Ansible et les jobs l'accepte.

### 3.1 Paquets nécessaires à la compilation

```bash
sudo dnf install -y gcc make tar curl openssl-devel bzip2-devel libffi-devel zlib-devel xz-devel sqlite-devel readline-devel
```

Ces paquets n'ajoutent que des outils et des en-têtes ; ils ne changent pas `python3`.

### 3.2 Télécharger Python

Prendre la dernière 3.11.x sur <https://www.python.org/downloads/> (les exemples utilisent 3.11.9, à remplacer). Une 3.9, 3.10 ou 3.12 convient aussi : adapter alors `3.11` partout dans cette fiche.

```bash
cd ~
curl -fLO https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
```

Comparer la somme de contrôle affichée sur la page de la version de python.org :

```bash
md5sum Python-3.11.9.tgz
```

**Sans accès Internet sur le bastion** : télécharger le fichier sur un autre poste, puis le copier. Dans PowerShell (sur Windows) :

```powershell
scp C:\chemin\Python-3.11.9.tgz admin01@192.168.50.10:~/
```

### 3.3 Compiler et installer (environ 5 minutes)

```bash
tar xzf Python-3.11.9.tgz
cd Python-3.11.9
./configure --prefix=/opt/python/3.11 --with-ensurepip=install
make -j"$(nproc)"
sudo make altinstall
cd ~
```

- `--prefix=/opt/python/3.11` : tout est installé dans ce dossier, rien dans `/usr`.
- `altinstall` crée `python3.11` et `pip3.11`, mais pas de commande `python3` : aucun risque de collision.
- Option `--enable-optimizations` (interpréteur environ 10 % plus rapide, compilation 5 à 10 fois plus longue) : inutile ici.

### 3.4 Vérifier Python local

```bash
/opt/python/3.11/bin/python3.11 --version
/opt/python/3.11/bin/python3.11 -c "import ssl, ctypes, sqlite3, venv; print(ssl.OPENSSL_VERSION)"
```

La première commande affiche `Python 3.11.9`. La seconde doit afficher la version d'OpenSSL sans erreur : un `ModuleNotFoundError: No module named '_ssl'` (ou `_ctypes`) signifie qu'un paquet `-devel` manquait pendant la compilation (voir le dépannage).

### 3.5 Variante : paquet AppStream (à utiliser sans la compilation 3.1 à 3.4)

```bash
sudo dnf install -y python3.11 python3.11-pip
python3.11 --version
python3 --version
```

Cette installation ajoute `/usr/bin/python3.11` mais ne change pas `python3` (toujours 3.6). Ne **jamais** lancer `alternatives --set python3 /usr/bin/python3.11`. Dans le reste de la fiche, remplacer `/opt/python/3.11/bin/python3.11` par `/usr/bin/python3.11`.

### 3.6 Variante : Python dans /home/sybase et service sous le compte `sybase`

Configuration retenue quand le scrutateur doit s'exécuter sous le compte `sybase` et que Python est installé dans son dossier personnel. Dans ce cas **aucun compte `scrutateur` n'est créé**. Préférer `/opt/python/3.11` et un compte dédié quand c'est possible : le scrutateur reçoit ici les droits du compte `sybase`, et son fichier de configuration (mots de passe) lui est lisible.

Vérifier d'abord le compte et son groupe : `id sybase` (la suite suppose un groupe principal `sybase` ; sinon, remplacer `sybase` par le groupe affiché après `gid=`).

**1. Compiler Python en tant que `sybase`** (les paquets de l'étape 3.1 sont à installer une fois par un compte `sudo`). À la place de 3.3, sous `sudo -iu sybase` :

```bash
tar xzf Python-3.11.9.tgz
cd Python-3.11.9
./configure --prefix=/home/sybase/python-3.11 --with-ensurepip=install
make -j"$(nproc)"
make altinstall
/home/sybase/python-3.11/bin/python3.11 --version
```

Aucun droit à ouvrir sur `/home/sybase` : le service s'exécute sous le même compte, qui lit déjà son dossier.

**2. Adapter les étapes 5.2, 5.5 et 5.6** (remplacer aussi `/opt/python/3.11` par `/home/sybase/python-3.11` dans 3.4, 5.2, 5.5, 9 et le dépannage) :

| Étape | À la place de | Écrire |
|---|---|---|
| 5.2 | `sudo useradd --system … scrutateur` | **ne pas l'exécuter** (pas de compte `scrutateur`) |
| 5.5 | `install -m 0640 -o root -g scrutateur …` | `sudo install -m 0640 -o root -g sybase scrutateur/deploy/scrutateur.env.example /etc/scrutateur/scrutateur.env` |
| 5.5 (partitions) | fichiers `/etc/scrutateur/partition-N.env` | `sudo chown root:sybase` et `sudo chmod 0640` sur chacun |
| 5.6 | `sudo -u scrutateur bash -c '…'` | `sudo -u sybase bash -c '…'` (même commande entre apostrophes) |

Le répertoire `/opt/scrutateur` (code et venv) reste propriété de `root` et lisible par tous : le service n'y écrit rien.

**3. Faire tourner le service sous `sybase`.** Les fichiers `scrutateur.service` et `scrutateur@.service` du dépôt indiquent `User=scrutateur` et `Group=scrutateur` : ne pas les modifier, ajouter un réglage local qui les remplace. Sans `Group=sybase`, systemd refuse de démarrer le service (`status=216/GROUP`). `ProtectHome=true` rend `/home` invisible au service : le passer en lecture seule.

```bash
sudo mkdir -p /etc/systemd/system/scrutateur.service.d /etc/systemd/system/scrutateur@.service.d
sudo tee /etc/systemd/system/scrutateur.service.d/sybase.conf > /dev/null <<'EOT'
[Service]
User=sybase
Group=sybase
ProtectHome=read-only
EOT
sudo cp /etc/systemd/system/scrutateur.service.d/sybase.conf /etc/systemd/system/scrutateur@.service.d/sybase.conf
sudo systemctl daemon-reload
systemctl show scrutateur -p User -p Group -p ProtectHome
```

La dernière commande doit afficher `User=sybase`, `Group=sybase`, `ProtectHome=read-only`. Le service ne lit pas le profil du compte (`.bash_profile`) : les variables d'environnement d'ASE (`SYBASE`, etc.) ne sont ni utilisées ni nécessaires.

**4. SELinux.** Les fichiers de `/home` portent le contexte `user_home_t`, que SELinux refuse en général d'exécuter depuis un service, même sous le compte propriétaire. Si `systemctl status scrutateur` affiche `status=203/EXEC` ou si `sudo ausearch -m avc -ts recent` montre un refus :

```bash
sudo semanage fcontext -a -t bin_t '/home/sybase/python-3.11(/.*)?'
sudo restorecon -Rv /home/sybase/python-3.11
```

Si `semanage` est absent : `sudo dnf install -y policycoreutils-python-utils`. Ne pas passer SELinux en `permissive` avant d'avoir lu les refus.

Le venv (créé en 5.2 avec ce Python) pointe vers `/home/sybase/python-3.11` : ne pas supprimer ni déplacer ce dossier tant que le scrutateur tourne.

## 4. Paquets système du bastion

```bash
sudo dnf install -y git postgresql
```

- `git` récupère le code ; `postgresql` fournit `psql`, pour les vérifications (version 10 par défaut du dépôt AppStream, suffisante pour tester la connexion à pg01) ;
- le scrutateur lui-même n'a besoin d'aucun paquet système : `psycopg[binary]` embarque `libpq` (ni ODBC ni FreeTDS).

## 5. Installer le scrutateur

### 5.1 Récupérer le code

```bash
cd ~
git clone https://github.com/serentz/RT_Meteo_PG.git
cd RT_Meteo_PG
```

Sans accès à GitHub, copier depuis Windows (PowerShell) puis, sur le bastion, se placer dans le dossier qui contient `scrutateur/` :

```powershell
scp -r I:\POC\RT_Meteo_PG\scrutateur I:\POC\RT_Meteo_PG\sql admin01@192.168.50.10:~/
```

### 5.2 Compte de service, dossiers, venv

```bash
sudo useradd --system --home-dir /opt/scrutateur --shell /sbin/nologin scrutateur   # ne pas exécuter si le service tourne sous sybase (3.6)
sudo mkdir -p /opt/scrutateur/app /etc/scrutateur
sudo cp -r scrutateur /opt/scrutateur/app/
sudo /opt/python/3.11/bin/python3.11 -m venv /opt/scrutateur/venv
sudo /opt/scrutateur/venv/bin/pip --version
```

`pip --version` doit citer `/opt/scrutateur/venv/lib/python3.11/site-packages/pip` et `(python 3.11)`.

Le venv pointe vers `/opt/python/3.11` : **ne pas supprimer ni déplacer ce dossier** tant que le scrutateur tourne.

### 5.3 Installer les modules Python (dans le venv seulement)

```bash
sudo /opt/scrutateur/venv/bin/pip install -r /opt/scrutateur/app/scrutateur/requirements.txt
sudo /opt/scrutateur/venv/bin/pip list
```

Le seul module externe est `psycopg[binary]` (`requirements.txt`) ; il embarque `libpq` et fournit un paquet binaire pour Python 3.11 sur RHEL 8 : aucun compilateur n'est nécessaire.

### 5.4 Sans accès à PyPI : installer depuis des fichiers copiés à la main

Sur un poste connecté (Linux ou Windows, avec Python 3.8 ou plus), dans un dossier vide :

```bash
pip download -r scrutateur/requirements.txt -d wheels --only-binary=:all: \
  --platform manylinux2014_x86_64 --python-version 3.11 --implementation cp --abi cp311
```

Copier le dossier `wheels` sur le bastion (`scp -r wheels admin01@192.168.50.10:~/`), puis :

```bash
sudo /opt/scrutateur/venv/bin/pip install --no-index --find-links ~/wheels -r /opt/scrutateur/app/scrutateur/requirements.txt
```

### 5.5 Configuration et service

```bash
sudo install -m 0640 -o root -g scrutateur scrutateur/deploy/scrutateur.env.example /etc/scrutateur/scrutateur.env
sudo install -m 0644 scrutateur/deploy/scrutateur.service /etc/systemd/system/scrutateur.service
sudo systemctl daemon-reload
sudo nano /etc/scrutateur/scrutateur.env
```

Dans le fichier, remplacer `CHANGER_MOI` par le mot de passe du rôle `scrutateur` de pg01 (ligne `SCRUTATEUR_STOCKAGE_DSN=postgresql://scrutateur:MOT_DE_PASSE@pg01:5432/meteo`). Si le mot de passe contient `@ : / ? # %`, encoder ces caractères dans l'URL (`@` devient `%40`) avec :

```bash
/opt/python/3.11/bin/python3.11 -c "import urllib.parse,getpass;print(urllib.parse.quote(getpass.getpass(),safe=''))"
```

Le service est déjà prévu pour ce chemin : `ExecStart=/opt/scrutateur/venv/bin/python -m scrutateur`, compte `scrutateur`, `ProtectSystem=strict`.

### 5.6 Essayer, puis démarrer

Essai d'une instance, sans rien écrire (remplacer `pg02` par le nom déclaré dans `meteo.instance`, majuscules comprises) :

```bash
sudo -u scrutateur bash -c 'set -a; . /etc/scrutateur/scrutateur.env; set +a; cd /opt/scrutateur/app && /opt/scrutateur/venv/bin/python -m scrutateur --tester pg02'
```

Un JSON avec les indicateurs s'affiche. Puis un cycle complet et le démarrage du service :

```bash
sudo -u scrutateur bash -c 'set -a; . /etc/scrutateur/scrutateur.env; set +a; cd /opt/scrutateur/app && /opt/scrutateur/venv/bin/python -m scrutateur --une-fois -v'
sudo systemctl enable --now scrutateur
sudo journalctl -u scrutateur -n 20 --no-pager
```

Le journal doit contenir `Cycle (partition 0/1) : N instance(s) lancee(s) sur N`, sans `WARNING` ni `ERROR`. Lecture du résultat, sur pg01 : `sudo -u postgres psql -d meteo -c "SELECT * FROM meteo.etat_instance"`.

Plusieurs scrutateurs (partition) : voir la section 5 de [scrutateur.md](scrutateur.md) ; seule différence, `/sbin/nologin` pour le compte, déjà créé ci-dessus.

## 6. Grafana

Installer le dépôt RPM et le paquet (RHEL ne reprend pas les commandes `apt` de [scrutateur.md](scrutateur.md), section 4.1) :

```bash
sudo tee /etc/yum.repos.d/grafana.repo > /dev/null <<'EOT'
[grafana]
name=grafana
baseurl=https://rpm.grafana.com
repo_gpgcheck=1
enabled=1
gpgcheck=1
gpgkey=https://rpm.grafana.com/gpg.key
sslverify=1
sslcacert=/etc/pki/tls/certs/ca-bundle.crt
EOT
sudo dnf install -y grafana
sudo grafana cli plugins install marcusolsson-dynamictext-panel
sudo systemctl enable --now grafana-server
```

Puis suivre les sections **4.2 à 4.4** de [scrutateur.md](scrutateur.md) sans changement (mêmes chemins `/etc/grafana`, `/var/lib/grafana`, `/usr/share/grafana`). Ouvrir le port et remettre les contextes SELinux des fichiers copiés :

```bash
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload
sudo restorecon -Rv /var/lib/grafana/dashboards /usr/share/grafana/public/img/meteo
sudo systemctl restart grafana-server
```

Écran : `http://ADRESSE_DU_BASTION:3000`.

## 7. Vérifier que le Python du système n'a pas changé

```bash
python3 --version
/usr/libexec/platform-python --version
ls -l /usr/bin/python* /usr/libexec/platform-python* > ~/python_apres.txt
rpm -qa 'python3*' | sort >> ~/python_apres.txt
sha256sum /usr/libexec/platform-python3.6 >> ~/python_apres.txt
diff ~/python_avant.txt ~/python_apres.txt && echo "Python systeme inchange"
```

Avec la méthode 3.1 à 3.4, `diff` ne doit afficher aucune différence (le Python local n'est pas un paquet RPM). Avec la variante 3.5, seules des lignes **ajoutées** (`python3.11…`) sont normales ; `python3` et `platform-python` restent identiques. Vérifier aussi le service : `systemctl is-active scrutateur` affiche `active`.

## 8. Dépannage propre à RHEL

| Symptôme | Cause et correction |
|---|---|
| `No module named '_ssl'`, `'_ctypes'` ou `'_sqlite3'` en 3.4 | Paquet `-devel` absent pendant `./configure`. Installer `openssl-devel libffi-devel sqlite-devel` (étape 3.1), puis `make distclean`, refaire `./configure … && make && sudo make altinstall`. |
| `pip install` : erreur SSL ou délai dépassé | Proxy ou certificat d'entreprise : `sudo /opt/scrutateur/venv/bin/pip --proxy http://PROXY:PORT install …`, ou `sudo /opt/scrutateur/venv/bin/pip config set global.cert /etc/pki/tls/certs/ca-bundle.crt`. Sinon, procédure 5.4. |
| `systemctl status scrutateur` : `status=203/EXEC` ou `Permission denied` | SELinux. Lister les refus : `sudo ausearch -m avc -ts recent`. Corriger le contexte : `sudo restorecon -Rv /opt/scrutateur /opt/python`. Si le refus persiste : `sudo semanage fcontext -a -t bin_t '/opt/python/3.11/bin(/.*)?'`, `sudo semanage fcontext -a -t bin_t '/opt/scrutateur/venv/bin(/.*)?'`, puis `restorecon -Rv` des deux dossiers. Ne pas passer SELinux en `permissive` ou `disabled` avant d'avoir lu les refus. |
| Le service ne se connecte pas à pg01 | Port 5432 filtré ou `pg_hba.conf` de pg01 (voir les sections 1.3 et 1.5 de [scrutateur.md](scrutateur.md)). Tester : `psql "postgresql://scrutateur@pg01:5432/meteo" -c "select 1"`. |
| Grafana inaccessible depuis le PC | Port 3000 fermé : commandes `firewall-cmd` de l'étape 6. |

## 9. Mettre à jour ou désinstaller

**Mise à jour du scrutateur** (nouveau code) : `git pull --ff-only`, puis `sudo cp -r scrutateur /opt/scrutateur/app/`, `sudo /opt/scrutateur/venv/bin/pip install -r /opt/scrutateur/app/scrutateur/requirements.txt` et `sudo systemctl restart scrutateur`.

**Mise à jour de Python local** (nouvelle 3.11.x) : refaire 3.2 à 3.4 avec la nouvelle archive et le même `--prefix=/opt/python/3.11`, puis `sudo /opt/python/3.11/bin/python3.11 -m venv --upgrade /opt/scrutateur/venv` et `sudo systemctl restart scrutateur`. Un changement de série (3.11 vers 3.12) demande un nouveau prefixe et un venv recréé.

**Désinstallation complète** (le Python du système n'est jamais concerné) :

```bash
sudo systemctl disable --now scrutateur
sudo rm -f /etc/systemd/system/scrutateur.service /etc/systemd/system/scrutateur@.service
sudo systemctl daemon-reload
sudo rm -rf /opt/scrutateur /etc/scrutateur /opt/python/3.11
sudo userdel scrutateur
```

## 10. Récapitulatif

| # | Étape | Machine | Contrôle |
|---|---|---|---|
| 1 | Noter l'état du Python système (2.1) | bastion | `~/python_avant.txt` créé |
| 2 | Compiler Python dans `/opt/python/3.11` (3 et sous-sections) | bastion | `python3.11 --version`, `import ssl` sans erreur |
| 3 | Paquets `dnf`, code, compte et venv (4, 5.1 à 5.3) | bastion | `pip list` dans le venv |
| 4 | Mot de passe, essai, service (5.5 et 5.6) | bastion | `--tester` en JSON, journal sans erreur |
| 5 | Grafana, port 3000, SELinux (6) | bastion | écran soleil / nuage / orage |
| 6 | Comparer l'état du Python système (7) | bastion | `Python systeme inchange` |
