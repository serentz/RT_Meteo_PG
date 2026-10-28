# RT_Meteo_PG

POC de monitoring PostgreSQL « météo temps réel » : un scrutateur Python (sur le bastion) relève chaque minute, en parallèle, les instances PostgreSQL listées dans une table de stockage ; Grafana restitue l'état sous forme soleil / nuage / orage. Même principe que [RT_Meteo_ASE](https://github.com/serentz/RT_Meteo_ASE), dont ce projet reprend toutes les fonctionnalités, avec PostgreSQL comme technologie surveillée.

## Infrastructure

Le script Hyper-V prépare trois VM Ubuntu et installe leurs OS. Il n'installe ni PostgreSQL, ni Grafana, ni le scrutateur (voir [docs/scrutateur.md](docs/scrutateur.md)).

| VM | OS prévu | IP par défaut | Ressources | Rôle cible |
|---|---|---|---|---|
| bastion | Ubuntu Server 24.04 LTS | 192.168.50.10 | 2 CPU, 4 Go, 30 Go | Scrutateur Python + Grafana |
| pg01 | Ubuntu Server 24.04 LTS | 192.168.50.11 | 2 CPU, 4 Go, 30 Go | PostgreSQL de **stockage** (schéma `meteo`) |
| pg02 | Ubuntu Server 24.04 LTS | 192.168.50.21 | 2 CPU, 4 Go, 30 Go | PostgreSQL **surveillé** (interrogé à distance, ni agent ni extension) |

Voir [Installation des VM](docs/installation_vm.md), [Scrutateur](docs/scrutateur.md), [Synchronisation Windows/GitHub](docs/transfert_github.md) et [Spécification du monitoring](docs/architecture.md).

## Fonctionnement

- Le scrutateur lit la table `meteo.instance` (nom, hôte, port, base, login, mot de passe) et, chaque minute, relève en parallèle toutes les instances actives.
- Une seule requête en lecture seule par relevé, sur `pg_stat_activity` et `pg_blocking_pids()` : aucune extension, aucun compteur cumulatif (rien n'est remis à zéro), le texte des requêtes n'est jamais lu.
- Cinq indicateurs par instance : temps max et moyen de blocage, temps max et moyen des requêtes en cours, temps max des transactions ouvertes (y compris les sessions « idle in transaction »).
- Chaque indicateur est comparé à des seuils (warning / alarme) : soleil, nuage, orage ; « inconnu » (lune) si la mesure manque ou est périmée. L'instance affiche son pire niveau.
- Le login de supervision doit être membre du rôle `pg_monitor`, sinon PostgreSQL masque les sessions des autres utilisateurs ; le scrutateur le contrôle et signale une erreur explicite plutôt qu'un faux soleil.

## Organisation

- `infra/hyperv/create_vms.ps1` et `infra/hyperv/templates/` : infrastructure et modèle d'installation Ubuntu.
- `infra/hyperv/check_vms.ps1` : diagnostic en lecture seule (Hyper-V, réseau de l'hôte, ping, port 22, bannière SSH).
- `images/iconnes/` : icônes météo (soleil, nuages, orages, lune endormie).
- `scrutateur/` : le script Python (une fonction par relevé d'instance, boucle parallèle), son service systemd et son modèle de configuration.
- `sql/cible/` : la requête exécutée sur chaque instance surveillée.
- `sql/stockage/` : schéma `meteo` (instances, mesures, processus, seuils, vues d'état, fonction d'écriture) et rôles.
- `grafana/` : provisioning (source PostgreSQL, tableaux de bord synthèse, liste et détail), voir [docs/scrutateur.md](docs/scrutateur.md).
- `tests/` : tests Python (`unittest`) et test SQL du schéma (`tests/stockage/test_schema.sql`).

## État de validation

Contrôlé dans l'environnement de préparation (Linux, PostgreSQL 16) : 60 tests Python et le test SQL du schéma passent ; la requête de supervision a été exécutée sur un vrai PostgreSQL avec des sessions bloquées, une requête longue, une transaction ouverte inactive et un login sans `pg_monitor`. **Non vérifié** : le pilote `psycopg` n'étant pas installable dans cet environnement, le scrutateur n'a pas été lancé de bout en bout (connexion réelle) ; les scripts PowerShell, les VM Hyper-V et le rendu Grafana restent à valider sur le PC de test (voir [docs/scrutateur.md](docs/scrutateur.md), section « Validation »).
