-- RT_Meteo_PG : schema de la base meteo (PostgreSQL 15 ou plus : UNIQUE NULLS NOT DISTINCT).
-- A executer une fois, en superutilisateur ou proprietaire de la base :
--   psql -d meteo -v ON_ERROR_STOP=1 -f sql/stockage/001_schema.sql
-- Rejouable : tout est CREATE ... IF NOT EXISTS / CREATE OR REPLACE.
-- Les droits (roles scrutateur et grafana_ro) sont dans 002_roles.sql.

CREATE SCHEMA IF NOT EXISTS meteo;

-- --- Instances PostgreSQL a surveiller ------------------------------------------------------
-- Le scrutateur releve chaque instance actif toutes les minutes, en parallele.
-- ATTENTION : login et password sont en clair (choix du POC). Ils ne sont lisibles que par
-- le role scrutateur et le proprietaire ; grafana_ro n'a aucun droit sur ces deux colonnes.
CREATE TABLE IF NOT EXISTS meteo.instance (
    instance_id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nom         text        NOT NULL UNIQUE,   -- nom affiche ; sert aussi de nom d'hote si host est NULL
    login       text        NOT NULL,
    password    text        NOT NULL,
    host        text,                          -- NULL : le scrutateur se connecte a <nom>
    port        integer     NOT NULL DEFAULT 5432 CHECK (port BETWEEN 1 AND 65535),
    base        text        NOT NULL DEFAULT 'postgres',  -- base de connexion (pg_stat_activity couvre toute l'instance)
    actif       boolean     NOT NULL DEFAULT true,
    cree_le     timestamptz NOT NULL DEFAULT now(),
    CHECK (btrim(nom) <> '')
);

-- --- Mesures : une ligne par instance et par releve --------------------------------------
-- statut 'ok'     : releve reussi ; aucun blocage / aucune requete en cours donne 0 (pas NULL).
-- statut 'erreur' : instance injoignable, login refuse, requete en echec... ; mesures a NULL.
CREATE TABLE IF NOT EXISTS meteo.mesure (
    mesure_id             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    instance_id           integer     NOT NULL REFERENCES meteo.instance ON DELETE CASCADE,
    collecte_le           timestamptz NOT NULL DEFAULT now(),
    duree_ms              integer,
    statut                text        NOT NULL CHECK (statut IN ('ok', 'erreur')),
    erreur                text,
    nb_bloques            integer,
    blocage_max_s         numeric,
    blocage_moyen_s       numeric,
    nb_requetes           integer,
    requete_max_s         numeric,
    requete_moyenne_s     numeric,
    CONSTRAINT mesure_coherente CHECK (
        (statut = 'ok' AND erreur IS NULL
            AND nb_bloques IS NOT NULL AND blocage_max_s IS NOT NULL AND blocage_moyen_s IS NOT NULL
            AND nb_requetes IS NOT NULL AND requete_max_s IS NOT NULL AND requete_moyenne_s IS NOT NULL)
        OR
        (statut = 'erreur' AND erreur IS NOT NULL
            AND nb_bloques IS NULL AND blocage_max_s IS NULL AND blocage_moyen_s IS NULL
            AND nb_requetes IS NULL AND requete_max_s IS NULL AND requete_moyenne_s IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS mesure_instance_date ON meteo.mesure (instance_id, collecte_le DESC);

-- --- Detail : le tableau lu sur l'instance a chaque releve (sessions avec requete en cours, bloquees, bloqueurs,
--     transactions ouvertes) ---
-- Volume : une ligne par session retenue et par releve (200 au plus) ; meteo.purger() limite la conservation.
CREATE TABLE IF NOT EXISTS meteo.processus (
    mesure_id         bigint  NOT NULL REFERENCES meteo.mesure ON DELETE CASCADE,
    pid               integer NOT NULL,
    login             text,             -- usename
    base              text,             -- datname
    statut            text,             -- state : active, idle in transaction...
    hote              text,             -- client_addr ('local' : socket)
    programme         text,             -- application_name
    attente           text,             -- wait_event_type:wait_event
    cmd               text,             -- premier mot de la derniere requete (jamais le texte complet)
    bloqueur_pid      integer,          -- NULL : pas bloquee
    blocage_s         integer,          -- NULL : pas bloquee
    execution_s       integer,          -- NULL : pas d'instruction en cours
    transaction_s     integer,          -- NULL : pas de transaction ouverte
    transaction_debut timestamp,        -- heure du serveur surveille, sans fuseau
    PRIMARY KEY (mesure_id, pid)
);

-- --- Indicateurs affiches et seuils -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meteo.indicateur (
    code    text    PRIMARY KEY,
    libelle text    NOT NULL,
    unite   text    NOT NULL,
    ordre   integer NOT NULL UNIQUE
);
INSERT INTO meteo.indicateur (code, libelle, unite, ordre) VALUES
    ('blocage_max',        'Temps max blocage',        's', 1),
    ('blocage_moyen',      'Temps moyen blocage',      's', 2),
    ('requete_max',        'Temps max requêtes',       's', 3),
    ('requete_moyenne',    'Temps moyen requêtes',     's', 4),
    ('transaction_max',    'Temps max transactions',   's', 5)
ON CONFLICT (code) DO NOTHING;

-- Seuils : valeur < warning : soleil ; warning <= valeur < alarme : nuage ; valeur >= alarme : orage.
-- instance_id NULL = seuil par defaut ; une ligne pour une instance le remplace.
CREATE TABLE IF NOT EXISTS meteo.seuil (
    instance_id integer REFERENCES meteo.instance ON DELETE CASCADE,
    indicateur  text    NOT NULL REFERENCES meteo.indicateur,
    warning     numeric NOT NULL,
    alarme      numeric NOT NULL,
    CHECK (warning >= 0 AND warning < alarme),
    UNIQUE NULLS NOT DISTINCT (instance_id, indicateur)
);
-- Valeurs initiales PROVISOIRES (secondes) : a ajuster selon la charge reelle.
INSERT INTO meteo.seuil (instance_id, indicateur, warning, alarme) VALUES
    (NULL, 'blocage_max',     30, 120),
    (NULL, 'blocage_moyen',   10,  60),
    (NULL, 'requete_max',     60, 300),
    (NULL, 'requete_moyenne', 120, 300),
    (NULL, 'transaction_max', 300, 900)
ON CONFLICT (instance_id, indicateur) DO NOTHING;

-- Parametres. peremption_s : au-dela, un releve est considere perime (3 cycles de 60 s).
CREATE TABLE IF NOT EXISTS meteo.parametre (
    cle    text    PRIMARY KEY,
    valeur numeric NOT NULL
);
INSERT INTO meteo.parametre (cle, valeur) VALUES ('peremption_s', 180)
ON CONFLICT (cle) DO NOTHING;

-- --- Fonction d'ecriture appelee par le scrutateur -----------------------------------------------
-- Un seul appel par instance et par cycle. SECURITY DEFINER : le role scrutateur n'a besoin que de
-- EXECUTE sur cette fonction (il n'a aucun droit direct d'ecriture sur les tables).
-- p_processus : tableau JSON d'objets {pid, login, base, statut, hote, programme, attente, cmd, bloqueur_pid,
--               blocage_s, execution_s, transaction_s, transaction_debut} (un par ligne du tableau lu sur l'instance).
CREATE OR REPLACE FUNCTION meteo.enregistrer_mesure(
    p_instance_id           integer,
    p_statut                text,
    p_erreur                text,
    p_duree_ms              integer,
    p_nb_bloques            integer,
    p_blocage_max_s         numeric,
    p_blocage_moyen_s       numeric,
    p_nb_requetes           integer,
    p_requete_max_s         numeric,
    p_requete_moyenne_s     numeric,
    p_processus             jsonb DEFAULT '[]'::jsonb
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = meteo, pg_temp
AS $$
DECLARE
    v_id bigint;
BEGIN
    INSERT INTO meteo.mesure (instance_id, duree_ms, statut, erreur, nb_bloques, blocage_max_s,
                              blocage_moyen_s, nb_requetes, requete_max_s, requete_moyenne_s)
    VALUES (p_instance_id, p_duree_ms, p_statut, p_erreur, p_nb_bloques, p_blocage_max_s,
            p_blocage_moyen_s, p_nb_requetes, p_requete_max_s, p_requete_moyenne_s)
    RETURNING mesure_id INTO v_id;

    IF p_statut = 'ok' AND jsonb_typeof(p_processus) = 'array' THEN
        INSERT INTO meteo.processus (mesure_id, pid, login, base, statut, hote, programme, attente, cmd,
                                     bloqueur_pid, blocage_s, execution_s, transaction_s, transaction_debut)
        SELECT v_id, (e->>'pid')::integer, e->>'login', e->>'base', e->>'statut', e->>'hote', e->>'programme',
               e->>'attente', e->>'cmd', (e->>'bloqueur_pid')::integer, (e->>'blocage_s')::integer,
               (e->>'execution_s')::integer, (e->>'transaction_s')::integer, (e->>'transaction_debut')::timestamp
        FROM jsonb_array_elements(p_processus) AS e;
    END IF;
    RETURN v_id;
END;
$$;
REVOKE ALL ON FUNCTION meteo.enregistrer_mesure(integer, text, text, integer, integer, numeric, numeric, integer, numeric, numeric, jsonb) FROM PUBLIC;

-- Purge : supprime les mesures plus anciennes que p_jours (les processus suivent en cascade).
-- A planifier (cron / pg_cron) ; non appelee automatiquement.
CREATE OR REPLACE FUNCTION meteo.purger(p_jours integer DEFAULT 30) RETURNS bigint
LANGUAGE sql AS $$
    WITH supprimees AS (
        DELETE FROM meteo.mesure WHERE collecte_le < now() - make_interval(days => p_jours) RETURNING 1
    )
    SELECT count(*) FROM supprimees;
$$;

-- --- Vues de restitution (Grafana / application web) ---------------------------------------------
-- Derniere mesure de chaque instance.
CREATE OR REPLACE VIEW meteo.derniere_mesure AS
SELECT DISTINCT ON (instance_id) *
FROM meteo.mesure
ORDER BY instance_id, collecte_le DESC, mesure_id DESC;

-- Une ligne par instance actif et par indicateur : valeur, seuils, niveau.
-- niveau : soleil | nuage | orage | inconnu. 'inconnu' si aucun releve, releve en erreur, releve perime
-- (plus vieux que parametre.peremption_s) ou seuils absents : jamais de faux soleil.
CREATE OR REPLACE VIEW meteo.etat_indicateur AS
WITH dm AS (
    SELECT m.*,
           (m.statut = 'ok'
            AND m.collecte_le >= now() - make_interval(secs => (SELECT valeur FROM meteo.parametre WHERE cle = 'peremption_s'))
           ) AS frais
    FROM meteo.derniere_mesure m
), valeurs AS (
    SELECT i.instance_id, i.nom, d.collecte_le, d.statut, d.erreur, d.frais, v.code, v.valeur
    FROM meteo.instance i
    LEFT JOIN dm d ON d.instance_id = i.instance_id
    CROSS JOIN LATERAL (VALUES
        ('blocage_max',         d.blocage_max_s),
        ('blocage_moyen',       d.blocage_moyen_s),
        ('requete_max',         d.requete_max_s),
        ('requete_moyenne',     d.requete_moyenne_s),
        -- Duree de la plus longue transaction ouverte du dernier releve (0 s'il n'y en a aucune ; NULL sans releve ok)
        ('transaction_max',     CASE WHEN d.statut = 'ok'
                                     THEN COALESCE((SELECT max(x.transaction_s) FROM meteo.processus x
                                                    WHERE x.mesure_id = d.mesure_id), 0) END)
    ) AS v(code, valeur)
    WHERE i.actif
)
SELECT va.instance_id,
       va.nom AS instance,
       ind.code AS indicateur,
       ind.libelle,
       ind.unite,
       ind.ordre,
       va.valeur,
       s.warning,
       s.alarme,
       va.collecte_le,
       va.statut,
       va.erreur,
       CASE
           WHEN NOT COALESCE(va.frais, false) OR va.valeur IS NULL OR s.alarme IS NULL THEN 'inconnu'
           WHEN va.valeur >= s.alarme  THEN 'orage'
           WHEN va.valeur >= s.warning THEN 'nuage'
           ELSE 'soleil'
       END AS niveau
FROM valeurs va
JOIN meteo.indicateur ind ON ind.code = va.code
LEFT JOIN LATERAL (
    SELECT sx.warning, sx.alarme
    FROM meteo.seuil sx
    WHERE sx.indicateur = va.code AND (sx.instance_id = va.instance_id OR sx.instance_id IS NULL)
    ORDER BY sx.instance_id NULLS LAST
    LIMIT 1
) s ON true;

-- Ecran de synthese : une ligne par instance, avec le pire niveau.
-- Ordre de gravite : orage > inconnu > nuage > soleil (une alarme connue prime ; on n'affiche
-- jamais soleil ni nuage si une mesure manque).
CREATE OR REPLACE VIEW meteo.etat_instance AS
SELECT e.instance_id,
       e.instance,
       CASE max(CASE e.niveau WHEN 'orage' THEN 3 WHEN 'inconnu' THEN 2 WHEN 'nuage' THEN 1 ELSE 0 END)
           WHEN 3 THEN 'orage'
           WHEN 2 THEN 'inconnu'
           WHEN 1 THEN 'nuage'
           ELSE 'soleil'
       END AS niveau,
       max(e.collecte_le) AS derniere_collecte,
       extract(epoch FROM now() - max(e.collecte_le))::integer AS age_s,
       (array_agg(e.statut) FILTER (WHERE e.statut IS NOT NULL))[1] AS statut,
       (array_agg(e.erreur) FILTER (WHERE e.erreur IS NOT NULL))[1] AS erreur
FROM meteo.etat_indicateur e
GROUP BY e.instance_id, e.instance;
