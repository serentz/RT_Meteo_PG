-- RT_Meteo_PG : roles et droits de la base meteo. A executer APRES 001_schema.sql, en superutilisateur, dans la base du POC.
-- Les mots de passe ne sont jamais ecrits dans ce fichier : ils sont passes en variables psql.
--   psql -d meteo -v ON_ERROR_STOP=1 \
--        -v pwd_scrutateur='...' -v pwd_grafana='...' -f sql/stockage/002_roles.sql
-- Caracteres a eviter dans ces mots de passe : apostrophe et antislash.

\if :{?pwd_scrutateur}
\else
  \echo 'Variable pwd_scrutateur absente (-v pwd_scrutateur=...)'
  \quit
\endif
\if :{?pwd_grafana}
\else
  \echo 'Variable pwd_grafana absente (-v pwd_grafana=...)'
  \quit
\endif

-- --- scrutateur : lit la liste des instances, appelle la fonction d'ecriture, rien d'autre ------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'scrutateur') THEN
        CREATE ROLE scrutateur LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
        CREATE ROLE grafana_ro LOGIN;
    END IF;
END
$$;
ALTER ROLE scrutateur PASSWORD :'pwd_scrutateur';
ALTER ROLE grafana_ro PASSWORD :'pwd_grafana';

-- Base de donnees courante : connexion autorisee uniquement a ces roles (en plus du proprietaire).
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO scrutateur, grafana_ro', current_database()) \gexec

REVOKE ALL ON SCHEMA meteo FROM PUBLIC;
GRANT USAGE ON SCHEMA meteo TO scrutateur, grafana_ro;

GRANT SELECT ON meteo.instance TO scrutateur;
GRANT EXECUTE ON FUNCTION meteo.enregistrer_mesure(integer, text, text, integer, integer, numeric, numeric, integer, numeric, numeric, jsonb) TO scrutateur;

-- --- grafana_ro : lecture seule, SANS acces aux colonnes login et password ---------------------------------
GRANT SELECT (instance_id, nom, host, port, base, actif, cree_le) ON meteo.instance TO grafana_ro;
GRANT SELECT ON meteo.mesure, meteo.processus, meteo.indicateur, meteo.seuil, meteo.parametre,
                meteo.derniere_mesure, meteo.etat_indicateur, meteo.etat_instance TO grafana_ro;
