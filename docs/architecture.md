# Architecture et règles du monitoring

```
 bastion (192.168.50.10)                       pg01 (192.168.50.11)        pg02 (192.168.50.21)
┌──────────────────────────┐   meteo.instance   ┌───────────────────┐      ┌──────────────────┐
│ scrutateur (Python)      │◄───────────────────│ PostgreSQL        │      │ PostgreSQL       │
│  1 relevé / instance /   │  meteo.enregistrer │  stockage         │      │  instance        │
│  minute, en parallèle    │───────────────────►│  schéma meteo     │      │  surveillée      │
│                          │   port 5432                                          ▲
│                          │──────────────────────────────────────────────────────┘
│ Grafana                  │◄── vues meteo.etat_instance / etat_indicateur (rôle grafana_ro)
└──────────────────────────┘
```

Le scrutateur tourne sur le bastion et interroge chaque instance PostgreSQL **à distance** : aucun agent, aucune extension, aucun objet créé sur pg02.

## Collecte

Intervalle : 60 secondes (`SCRUTATEUR_INTERVALLE_S`), cadence fixe sans dérive. À chaque cycle, le scrutateur relit la table `meteo.instance` ; une instance ajoutée, modifiée ou désactivée (`actif`) est prise en compte au cycle suivant sans redémarrage.

| Colonne de `meteo.instance` | Rôle |
|---|---|
| `nom` | nom de l'instance, affiché ; sert aussi de nom d'hôte si `host` est vide |
| `login`, `password` | login PostgreSQL de supervision (membre de `pg_monitor`) |
| `host`, `port` | adresse de connexion si elle diffère du nom ; port 5432 par défaut |
| `base` | base de connexion (`postgres` par défaut) ; sans effet sur le résultat, la vue `pg_stat_activity` couvrant toute l'instance |
| `actif` | `false` : l'instance n'est plus relevée ni affichée |

**Parallélisme.** Chaque instance est relevée dans son propre thread (16 au maximum, `SCRUTATEUR_MAX_PARALLELE`). La panne ou la lenteur d'une instance ne retarde pas les autres. Si le relevé précédent d'une instance n'est pas terminé, elle est sautée au lieu d'empiler des relevés. Les délais de connexion (10 s) et de requête (15 s, `statement_timeout` côté serveur, pour le contrôle des droits puis la requête principale) bornent la durée d'un relevé à 40 s.

**Passage à l'échelle.** Les départs des relevés d'un cycle sont répartis sur `SCRUTATEUR_ETALEMENT_S` (20 s) au lieu d'une rafale à la même seconde. Plusieurs scrutateurs peuvent se partager les instances (`SCRUTATEUR_PARTITION=i/N` : instance_id % N = i), sans coordination ; un avertissement signale quand il y a plus de relevés en cours que de threads. Dimensionnement : `docs/scrutateur.md`, section 5.

**Unité de travail.** `collecter_et_enregistrer(instance, source, depot)` (module `scrutateur/collecte.py`) relève une instance et met à jour le stockage ; elle ne lève jamais d'exception. Un échec devient une mesure `erreur`. L'écriture se fait par un seul appel à la fonction SQL `meteo.enregistrer_mesure(...)`.

**Source : une requête principale** sur `pg_stat_activity` et `pg_blocking_pids()` (texte dans `sql/cible/supervision.sql`). Elle rend un tableau, lu en mémoire par le scrutateur ; c'est de ce tableau que sont calculés tous les indicateurs et que vient le détail des processus. Colonnes :

- `pid`, `login` (`usename`), `base` (`datname`), `statut` (`state`), `programme` (`application_name`), `hote` (`client_addr`), `attente` (`wait_event_type:wait_event`), `cmd` (premier mot de la requête : SELECT, UPDATE...) ;
- `bloqueur_pid` : premier bloqueur renvoyé par `pg_blocking_pids`, 0 si la session n'est pas bloquée ; `blocage_s` : secondes depuis le début de l'instruction bloquée ;
- `execution_s` : secondes depuis le début de l'instruction, **seulement pour une session `active`** (sinon vide) ;
- `transaction_s` et `transaction_debut` : durée et heure de début (heure du serveur surveillé) de la transaction ouverte, y compris une session `idle in transaction`.

Lignes retenues : instruction en cours, ou transaction ouverte, ou session bloquée, ou **bloqueur** d'une autre session (un bloqueur est souvent inactif ; sans cette clause il resterait anonyme). Sont exclus : la connexion du scrutateur (`pg_backend_pid()`) et tout ce qui n'est pas une session cliente (autovacuum, walsender, checkpointer...).

**Réserves.**

- `blocage_s` est une **approximation** : PostgreSQL n'indique pas depuis quand une session attend un verrou ; la valeur est la durée de l'instruction bloquée, donc une borne haute de l'attente réelle.
- Sans `pg_monitor` (ou superutilisateur), PostgreSQL masque `state`, `query` et `xact_start` des sessions des autres utilisateurs : le tableau serait faussement vide. Le scrutateur contrôle ce droit (`SQL_DROITS`) avant la requête principale et lève une erreur explicite (`DroitsInsuffisants`) : l'instance passe en « inconnu ».
- Le détail conservé est limité à 200 lignes (bloquées d'abord, puis transactions, puis requêtes les plus longues) ; les indicateurs, eux, sont calculés sur toutes les lignes.

**Impact minimal sur les instances.** Météo temps réel doit rester légère. Par relevé : une connexion, deux `SELECT` en lecture seule (contrôle des droits, puis la requête principale), en autocommit, puis fermeture. La connexion est ouverte avec `default_transaction_read_only=on` et un `statement_timeout`. Aucune écriture, aucune extension (`pg_stat_statements` non requis), aucune table temporaire, aucune modification de la configuration, **aucun compteur cumulatif lu ni remis à zéro**, et le texte des requêtes n'est jamais lu (il peut contenir des données) : seul son premier mot est conservé. Au plus un relevé par minute et par instance. Cette règle prime sur l'ajout d'indicateurs : un indicateur qui exigerait une extension ou la lecture des requêtes est hors périmètre.

**Sécurité.** Les identifiants des instances surveillées sont en clair dans `meteo.instance` (choix du POC). Seul le rôle `scrutateur` du stockage les lit ; `grafana_ro` n'a aucun droit sur les colonnes `login` et `password`. Utiliser sur chaque instance un login dédié, membre de `pg_monitor` et sans autre droit. Le mot de passe du rôle `scrutateur` du stockage est dans `/etc/scrutateur/scrutateur.env` (mode 0640, hors Git). Les mots de passe ne figurent jamais dans les journaux ni dans les messages d'erreur stockés.

## Indicateurs affichés

| Indicateur (`code`) | Définition | Unité |
|---|---|---|
| Temps max blocage (`blocage_max`) | Maximum de `blocage_s` des sessions actuellement bloquées | secondes |
| Temps moyen blocage (`blocage_moyen`) | Moyenne sur les seules sessions actuellement bloquées | secondes |
| Temps max requêtes (`requete_max`) | Maximum de `execution_s` des sessions `active` (bloquées comprises) | secondes |
| Temps moyen requêtes (`requete_moyenne`) | Moyenne sur ces mêmes sessions | secondes |
| Temps max transactions (`transaction_max`) | Durée de la plus longue transaction ouverte du dernier relevé (`idle in transaction` comprises) ; 0 s'il n'y en a aucune | secondes |

Un relevé réussi sans blocage ni requête en cours donne zéro. Une mesure indisponible donne NULL et l'état « inconnu ». Le tableau lu est conservé dans `meteo.processus` à chaque relevé : requêtes actives, sessions bloquées, bloqueurs et transactions ouvertes, avec base, hôte, programme, login, commande, attente, bloqueur et durées. Le bloqueur est identifiable même s'il est inactif.

## Seuils et écrans

Pour chaque indicateur : seuil warning W et seuil alarme A, avec 0 <= W < A, dans `meteo.seuil`. Une ligne sans `instance_id` est le seuil par défaut ; une ligne pour une instance le remplace. Valeur < W : soleil ; W <= valeur < A : nuage ; valeur >= A : orage.

Valeurs initiales **provisoires** (secondes), à ajuster selon la charge :

| Indicateur | W | A |
|---|---|---|
| blocage max | 30 | 120 |
| blocage moyen | 10 | 60 |
| requête max | 60 | 300 |
| requête moyenne | 120 | 300 |
| transaction max | 300 | 900 |

Les vues `meteo.etat_indicateur` (une ligne par instance et par indicateur : valeur, seuils, niveau) et `meteo.etat_instance` (une ligne par instance : pire niveau) alimentent l'affichage. Le niveau est `soleil`, `nuage`, `orage` ou `inconnu`.

**État inconnu.** Il s'affiche si l'instance n'a jamais été relevée, si le dernier relevé est en erreur, s'il est périmé ou si les seuils manquent : il n'y a jamais de faux soleil. La péremption est de 180 secondes (3 cycles), réglable dans `meteo.parametre` (`peremption_s`). Le message d'erreur et la date du dernier relevé sont dans les vues.

**Niveau d'une instance.** Il reprend le plus grave de ses indicateurs, dans l'ordre orage > inconnu > nuage > soleil : une alarme connue prime, mais on n'affiche jamais soleil ni nuage s'il manque une mesure. L'icône « inconnu » est la lune endormie (`images/iconnes/lune_dors.png`).

Dans Grafana (`grafana/`) : la synthèse affiche une tuile par instance (icône, nom dessous, âge du relevé) cliquable vers le détail (greffon Business Text) ; la liste en est la version sans greffon ; le détail montre l'état, un indicateur par ligne (valeur, unité, seuils, icône), les sessions du dernier relevé puis les transactions ouvertes de la plus longue à la plus courte.

## Acceptation fonctionnelle

1. Instance sans anomalie : soleil et cinq valeurs valides.
2. Blocage contrôlé (voir `docs/scrutateur.md`, 2.6) : nuage puis orage aux seuils, avec bloqueur identifiable dans `meteo.processus`.
3. Requête longue (`pg_sleep`) : sa durée apparaît dans le détail et dans les indicateurs requête max et moyenne, cohérente avec `pg_stat_activity` lu sous `psql`.
4. Transaction ouverte inactive : elle apparaît dans le tableau des transactions et alimente `transaction_max`.
5. Instance injoignable, login refusé, droits `pg_monitor` absents ou stockage indisponible : aucun faux soleil ; retour à la normale après reprise et relevé valide.
6. Parallélisme : une instance lente ou en panne ne retarde pas le relevé des autres.
7. Instance ajoutée ou désactivée dans `meteo.instance` : prise en compte sans redémarrage.

Les points 5 (partiellement), 6 et 7 sont couverts par les tests automatiques ; les points 1 à 4 demandent une vraie instance (voir `docs/scrutateur.md`, section « Validation »).
