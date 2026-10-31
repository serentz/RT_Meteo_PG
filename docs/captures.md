# Captures d'écran (Release 1)

Captures prises sur les VM de test (PostgreSQL 16.15 sur Ubuntu 24.04, scrutateur et Grafana sur le bastion), dans `images/Release1/`. Deux instances sont surveillées : `pg01` (qui héberge aussi le stockage) et `pg02`, sur laquelle les scénarios sont joués. Les scénarios et leurs commandes sont décrits dans [scrutateur.md](scrutateur.md) (section 2.6). Pour obtenir un orage rapidement, les seuils de `blocage_max`, `requete_max` et `transaction_max` avaient été abaissés à 10/30, 10/30 et 15/60 s (valeurs par défaut : 30/120, 60/300 et 300/900), puis restaurés.

## Synthèse

| Image | Scénario | Ce que l'on voit |
|---|---|---|
| [01_soleil.png](../images/Release1/01_soleil.png) | Aucune anomalie | Tuiles `pg01` et `pg02` : soleil, bordure verte. |
| [03_requete_longue_synthese.png](../images/Release1/03_requete_longue_synthese.png) | `SELECT pg_sleep(400)` sur `pg02` | `pg02` : orage, bordure rouge ; `pg01` reste au soleil, et passe après `pg02` (pires états en premier). |
| [05_blocage_synthese.png](../images/Release1/05_blocage_synthese.png) | Une session bloque une autre | `pg02` : orage ; `pg01` : soleil. |
| [09_retour_soleil_synthese.png](../images/Release1/09_retour_soleil_synthese.png) | Fin du blocage (`ROLLBACK`) | Les deux instances sont revenues au soleil. |
| [10_arret_synthese.png](../images/Release1/10_arret_synthese.png) | PostgreSQL arrêté sur `pg02` | `pg02` : lune endormie (inconnu), « relevé en erreur » ; `pg01` : soleil. |
| [12_reprise_synthese.png](../images/Release1/12_reprise_synthese.png) | PostgreSQL redémarré | Les deux instances au soleil. |

## Détail d'une instance (`pg02`)

| Image | Scénario | Ce que l'on voit |
|---|---|---|
| [02_detail_soleil.png](../images/Release1/02_detail_soleil.png) | Aucune anomalie | Cinq indicateurs à 0 s, avec leurs seuils ; « Aucune requête en cours ni blocage ». |
| [04_requete_longue_detail.png](../images/Release1/04_requete_longue_detail.png) | Requête longue | Temps max des requêtes et des transactions à 66 s : orage ; temps moyen des requêtes : soleil (seuil 120 s). Le tableau des processus montre le `SELECT` en attente `Timeout:PgSleep`. |
| [06_blocage_detail.png](../images/Release1/06_blocage_detail.png) | Blocage | Le bloqué (pid 5496, `UPDATE`, attente `Lock:transactionid`) est « bloqué par » 5490, le bloqueur, `idle in transaction`, identifié. Temps max de blocage 56 s : orage ; temps moyen de blocage : nuage ; transaction du bloqueur : 69 s. |
| [07_transaction_ouverte_detail.png](../images/Release1/07_transaction_ouverte_detail.png) | Transaction ouverte inactive (`BEGIN; UPDATE …`) | Aucune requête en cours ; le tableau des transactions montre la session `idle in transaction` depuis 140 s : « Temps max transactions » en orage (seuil abaissé à 60 s). |
| [08_retour_soleil_detail.png](../images/Release1/08_retour_soleil_detail.png) | Après `ROLLBACK` | Tous les indicateurs à 0 : soleil ; plus aucun processus ni transaction. |
| [11_arret_detail.png](../images/Release1/11_arret_detail.png) | PostgreSQL arrêté | État `inconnu`, relevé en `erreur` (`OperationalError: connection failed`), cinq indicateurs `inconnu`, tableaux sans données. |
| [13_reprise_detail.png](../images/Release1/13_reprise_detail.png) | PostgreSQL redémarré | État `soleil`, relevé `ok`, seuils par défaut rétablis (30/120, 60/300, 300/900). |

Pour remplacer une capture : garder le nom du fichier, remplacer l'image, mettre à jour la légende ci-dessus.
