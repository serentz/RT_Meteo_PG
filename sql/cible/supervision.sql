-- Requete de supervision d'une instance POSTGRESQL surveillee : la SEULE executee par le scrutateur sur chaque instance.
-- Une connexion, un SELECT en lecture seule sur pg_stat_activity (+ pg_blocking_pids), puis fermeture.
-- Aucune extension (pas de pg_stat_statements), aucune vue de statistiques cumulatives : rien n'est remis a zero
-- et les outils de supervision deja en place ne sont pas perturbes. Meteo temps reel doit rester legere.
--
-- Colonnes : pid, login (usename), base (datname), statut (state), programme (application_name), hote (client_addr),
--   attente (wait_event_type:wait_event), cmd (premier mot de la requete : SELECT, UPDATE...), bloqueur_pid (premier
--   bloqueur, 0 si la session n'est pas bloquee), blocage_s (secondes depuis le debut de l'instruction bloquee),
--   execution_s (secondes depuis le debut de l'instruction, session active seulement, sinon NULL),
--   transaction_s (secondes depuis le debut de la transaction ouverte, sinon NULL), transaction_debut (heure du
--   serveur surveille, 'AAAA-MM-JJ HH:MM:SS').
-- Le texte des requetes n'est PAS lu : il peut contenir des donnees ; seul son premier mot est conserve.
--
-- Lignes retenues : instruction en cours, ou transaction ouverte (y compris "idle in transaction"), ou session
-- bloquee, ou bloqueur d'une autre session (souvent inactif : sans cette clause il resterait anonyme).
-- Exclus : la connexion du scrutateur (pg_backend_pid()) et tout ce qui n'est pas une session cliente
-- (autovacuum, walsender, checkpointer, bgwriter...).
--
-- Droits : le login de supervision doit etre membre du role predefini pg_monitor (PostgreSQL >= 10), sinon
-- PostgreSQL masque state, query et xact_start des sessions des autres utilisateurs :
--   CREATE ROLE scrutateur LOGIN PASSWORD '<mot_de_passe>';  GRANT pg_monitor TO scrutateur;
-- Le scrutateur controle ce droit avant la requete (SQL_DROITS dans scrutateur/cible.py) et signale une erreur claire s'il manque.
-- Il calcule les indicateurs sur toutes les lignes mais n'en conserve que 200 dans le detail (bloquees et plus longues d'abord).
--
-- Approximation : PostgreSQL n'indique pas depuis quand une session attend un verrou. blocage_s = duree de l'instruction
-- bloquee (borne haute de l'attente reelle).
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
ORDER BY s.pid;
