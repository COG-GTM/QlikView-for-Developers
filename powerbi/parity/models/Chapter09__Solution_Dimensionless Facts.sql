-- Source model for Chapter09/Solution_Dimensionless Facts.qvw (load script: inventory/scripts/).
-- Aircrafts = Aircrafts.csv plus one 'Unknown' row per Flights key that has no Aircrafts row
-- (Temp_Aircraft_Type_ID + CONCATENATE LOAD DISTINCT ... WHERE NOT Exists(Temp_Aircraft_Type_ID, ...)).
-- The 'Unknown: ' & key label uses the key's text as QlikView read it from Flights.csv: zero-padded to
-- 3 digits ('007'); the Parquet holds the number, so the text is rebuilt with printf('%03d').

CREATE VIEW "Flights" AS
SELECT "Year", "Month (#)", "%Aircraft Type ID", "# Departures Scheduled", "# Departures Performed",
       "# Available Seats", "# Transported Passengers", "# Transported Freight"
FROM read_parquet('{parquet}/Chapter09/Flights.parquet');

CREATE VIEW "Aircrafts" AS
WITH listed AS (
    SELECT "AC_TYPEID" AS "%Aircraft Type ID", "Aircraft Group", "Manufacturer", "Aircraft Name", "Aircraft Short Name"
    FROM read_parquet('{parquet}/Chapter09/Aircrafts.parquet')
)
SELECT * FROM listed
UNION ALL
SELECT DISTINCT f."%Aircraft Type ID",
       'Unknown' AS "Aircraft Group",
       'UNKNOWN' AS "Manufacturer",
       'Unknown: ' || printf('%03d', f."%Aircraft Type ID") AS "Aircraft Name",
       '???' AS "Aircraft Short Name"
FROM "Flights" AS f
WHERE f."%Aircraft Type ID" NOT IN (SELECT "%Aircraft Type ID" FROM listed);
