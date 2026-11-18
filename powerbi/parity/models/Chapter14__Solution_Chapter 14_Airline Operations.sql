-- Source model for Chapter14/Solution_Chapter 14_Airline Operations.qvw, reproducing its load script
-- (inventory/scripts/Chapter14__Solution_Chapter 14_Airline Operations.qvs) independently of the Power Query.
--
-- Chapter 14 runs the Chapter 15 script without its hidden Section Access tab (the stored model has no Section
-- Access and no INLFED flight-type table), so nothing is reduced: the .qvw's stored row counts are the unreduced
-- Main Data 1,258,763; Airlines 337; Carrier Operating Region 8; Origin / Destination Markets 1,860 / 1,918.
-- Everything the script loads is built in schema `src`; the views the harness reads (schema main) expose it as is.

CREATE SCHEMA src;

-- [Main Data]: Flight Data.qvd, then Concatenate Employment Statistics.QVD (Year / Month (#) / Month / Quarter are
-- commented out in both loads).
CREATE VIEW src."Main Data" AS
SELECT "%Airline ID", "%Carrier Group ID", "%Unique Carrier Code", "%Unique Carrier Entity Code", "%Region Code",
       "%Origin Airport ID", "%Origin Airport Sequence ID", "%Origin Airport Market ID", "%Origin World Area Code",
       "%Destination Airport ID", "%Destination Airport Sequence ID", "%Destination Airport Market ID",
       "%Destination World Area Code", "%Aircraft Group ID", "%Aircraft Type ID", "%Aircraft Configuration ID",
       "%Distance Group ID", "%Service Class ID", "%Datasource ID",
       "# Departures Scheduled", "# Departures Performed", "# Payload", "Distance", "# Available Seats",
       "# Transported Passengers", "# Transported Freight", "# Transported Mail", "# Ramp-To-Ramp Time", "# Air Time",
       "Unique Carrier", "Carrier Code", "Carrier Name",
       "Origin Airport Code", "Origin City", "Origin State Code", "Origin State FIPS", "Origin State",
       "Origin Country Code", "Origin Country",
       "Destination Airport Code", "Destination City", "Destination State Code", "Destination State FIPS",
       "Destination State", "Destination Country Code", "Destination Country",
       "Period", "From - To Airport Code", "From - To Airport ID", "From - To City", "From - To State Code",
       "From - To State",
       NULL::BIGINT AS "# M-Delta Total Employees", NULL::BIGINT AS "# M-Delta Full Time Employees",
       NULL::BIGINT AS "# M-Delta Part Time Employees", NULL::BIGINT AS "# M-Delta Equivalent FTEs",
       NULL::BIGINT AS "# Q-Delta Total Employees", NULL::BIGINT AS "# Q-Delta Full Time Employees",
       NULL::BIGINT AS "# Q-Delta Part Time Employees", NULL::BIGINT AS "# Q-Delta Equivalent FTEs",
       NULL::BIGINT AS "# Y-Delta Total Employees", NULL::BIGINT AS "# Y-Delta Full Time Employees",
       NULL::BIGINT AS "# Y-Delta Part Time Employees", NULL::BIGINT AS "# Y-Delta Equivalent FTEs",
       NULL::BIGINT AS "# Total Employees", NULL::BIGINT AS "# Full Time Employees",
       NULL::BIGINT AS "# Part Time Employees", NULL::BIGINT AS "# Equivalent FTEs"
FROM read_parquet('{parquet}/QVD/Source/Flight Data.parquet')
UNION ALL BY NAME
SELECT "# M-Delta Total Employees", "# M-Delta Full Time Employees", "# M-Delta Part Time Employees",
       "# M-Delta Equivalent FTEs", "# Q-Delta Total Employees", "# Q-Delta Full Time Employees",
       "# Q-Delta Part Time Employees", "# Q-Delta Equivalent FTEs", "# Y-Delta Total Employees",
       "# Y-Delta Full Time Employees", "# Y-Delta Part Time Employees", "# Y-Delta Equivalent FTEs",
       "%Airline ID", "# Total Employees", "Period", "%Unique Carrier Code", "Unique Carrier", "Carrier Code",
       "Carrier Name", "%Carrier Group ID", "# Full Time Employees", "# Part Time Employees", "# Equivalent FTEs"
FROM read_parquet('{parquet}/QVD/Transformed/Employment Statistics.parquet');

-- [Master Calendar]: one row per *day* from MonthStart(min Period) to MonthStart(max Period). The script's
-- LOAD DISTINCTs sit under a non-distinct preceding `Load *`, so Qlik keeps the daily duplicates (1065 rows).
CREATE VIEW src."Master Calendar" AS
WITH rng AS (
    SELECT strptime(CAST(min("Period") AS VARCHAR), '%Y%m')::DATE AS lo,
           strptime(CAST(max("Period") AS VARCHAR), '%Y%m')::DATE AS hi
    FROM src."Main Data"
), days AS (
    SELECT date_trunc('month', d)::DATE AS m, d
    FROM rng, generate_series(lo::TIMESTAMP, hi::TIMESTAMP, INTERVAL 1 DAY) AS g(d)
)
SELECT year(m) * 100 + month(m)                                   AS "Period",
       year(m)                                                    AS "Year",
       strftime(m, '%b')                                          AS "Month",
       CAST(month(m) AS DOUBLE)                                   AS "Month__num",
       strftime(m, '%Y-%m')                                       AS "Year - Month",
       CAST(m - DATE '1899-12-30' AS DOUBLE)                      AS "Year - Month__num",
       'Q' || CAST(ceil(month(m) / 3) AS INTEGER)                 AS "Quarter",
       dense_rank() OVER (ORDER BY year(m), ceil(month(m) / 3))   AS "QuarterID",
       dense_rank() OVER (ORDER BY m)                             AS "PeriodID"
FROM days;

-- Dimension tables: WHERE Exists(<key>) against the key values of [Main Data]; four of them then concatenate an
-- 'Unknown' member for every [Main Data] key value missing from the dimension. NOT Exists(Temp, key) is also true
-- for a null key, so Qlik adds a null-key 'Unknown' row when [Main Data] has null keys.
CREATE VIEW src."Carrier Groups" AS
WITH src AS (
    SELECT "%Carrier Group ID", "Carrier Group" FROM read_parquet('{parquet}/QVD/Source/Carrier Groups.parquet')
    WHERE "%Carrier Group ID" IN (SELECT "%Carrier Group ID" FROM src."Main Data")
)
SELECT * FROM src
UNION ALL
SELECT DISTINCT "%Carrier Group ID", 'Unknown' FROM src."Main Data"
WHERE "%Carrier Group ID" IS NULL OR "%Carrier Group ID" NOT IN (SELECT "%Carrier Group ID" FROM src);

CREATE VIEW src."Airlines" AS
SELECT "%Airline ID", "Airline" FROM read_parquet('{parquet}/QVD/Source/Airlines.parquet')
WHERE "%Airline ID" IN (SELECT "%Airline ID" FROM src."Main Data");

CREATE VIEW src."Carrier Operating Region" AS
WITH src AS (
    SELECT "%Region Code", "Carrier's Operating Region"
    FROM read_parquet('{parquet}/QVD/Source/Carrier Operating Region.parquet')
    WHERE "%Region Code" IN (SELECT "%Region Code" FROM src."Main Data")
)
SELECT * FROM src
UNION ALL
SELECT DISTINCT "%Region Code", 'Unknown' FROM src."Main Data"
WHERE "%Region Code" IS NULL OR "%Region Code" NOT IN (SELECT "%Region Code" FROM src);

CREATE VIEW src."Flight Types" AS
SELECT "%Datasource ID", "Flight Type" FROM read_parquet('{parquet}/QVD/Source/Flight Types.parquet')
WHERE "%Datasource ID" IN (SELECT "%Datasource ID" FROM src."Main Data");

CREATE VIEW src."Aircraft Types" AS
SELECT "%Aircraft Type ID", "Aircraft Name", "Aircraft Manufacturer", "Aircraft Manufacturer Country",
       "Aircraft Name Full", "Aircraft Name Abbreviated", "Aircraft Begin Date", "Aircraft End Date",
       "Aircraft Age Classification", "Aircraft Engine Type", "Aircraft Number Of Engines"
FROM read_parquet('{parquet}/QVD/Transformed/Aircraft Types Transformed.parquet')
WHERE "%Aircraft Type ID" IN (SELECT "%Aircraft Type ID" FROM src."Main Data");

CREATE VIEW src."Distance Groups" AS
SELECT "%Distance Group ID", "Distance Interval" FROM read_parquet('{parquet}/QVD/Source/Distance Groups.parquet')
WHERE "%Distance Group ID" IN (SELECT "%Distance Group ID" FROM src."Main Data");

CREATE VIEW src."Origin Airports" AS
SELECT "%Origin Airport ID", "Origin Airport" FROM read_parquet('{parquet}/QVD/Source/Origin Airports.parquet')
WHERE "%Origin Airport ID" IN (SELECT "%Origin Airport ID" FROM src."Main Data");

CREATE VIEW src."Destination Airports" AS
SELECT "%Destination Airport ID", "Destination Airport"
FROM read_parquet('{parquet}/QVD/Source/Destination Airports.parquet')
WHERE "%Destination Airport ID" IN (SELECT "%Destination Airport ID" FROM src."Main Data");

CREATE VIEW src."Origin Markets" AS
WITH src AS (
    SELECT "%Origin Airport Market ID", "Origin Market" FROM read_parquet('{parquet}/QVD/Source/Origin Markets.parquet')
    WHERE "%Origin Airport Market ID" IN (SELECT "%Origin Airport Market ID" FROM src."Main Data")
)
SELECT * FROM src
UNION ALL
SELECT DISTINCT "%Origin Airport Market ID", 'Unknown' FROM src."Main Data"
WHERE "%Origin Airport Market ID" IS NULL
   OR "%Origin Airport Market ID" NOT IN (SELECT "%Origin Airport Market ID" FROM src);

CREATE VIEW src."Destination Markets" AS
WITH src AS (
    SELECT "%Destination Airport Market ID", "Destination Market"
    FROM read_parquet('{parquet}/QVD/Source/Destination Markets.parquet')
    WHERE "%Destination Airport Market ID" IN (SELECT "%Destination Airport Market ID" FROM src."Main Data")
)
SELECT * FROM src
UNION ALL
SELECT DISTINCT "%Destination Airport Market ID", 'Unknown' FROM src."Main Data"
WHERE "%Destination Airport Market ID" IS NULL
   OR "%Destination Airport Market ID" NOT IN (SELECT "%Destination Airport Market ID" FROM src);

-- Inline table: the metric picker, named INLFED here (INLFED-1 in Chapter 15, where Section Access loads INLFED first).
CREATE VIEW src."INLFED" AS
SELECT * FROM (VALUES ('# of Flights', 'eDeparturesPerformed'), ('Enplaned Passengers', 'eEnplanedPassengers'),
                      ('Air Time', 'eAirTime')) AS t("Metric Name", "eMetric");

CREATE VIEW "Main Data" AS SELECT * FROM src."Main Data";
CREATE VIEW "Master Calendar" AS SELECT * FROM src."Master Calendar";
CREATE VIEW "Carrier Groups" AS SELECT * FROM src."Carrier Groups";
CREATE VIEW "Airlines" AS SELECT * FROM src."Airlines";
CREATE VIEW "Carrier Operating Region" AS SELECT * FROM src."Carrier Operating Region";
CREATE VIEW "Flight Types" AS SELECT * FROM src."Flight Types";
CREATE VIEW "Aircraft Types" AS SELECT * FROM src."Aircraft Types";
CREATE VIEW "Distance Groups" AS SELECT * FROM src."Distance Groups";
CREATE VIEW "Origin Airports" AS SELECT * FROM src."Origin Airports";
CREATE VIEW "Destination Airports" AS SELECT * FROM src."Destination Airports";
CREATE VIEW "Origin Markets" AS SELECT * FROM src."Origin Markets";
CREATE VIEW "Destination Markets" AS SELECT * FROM src."Destination Markets";
CREATE VIEW "INLFED" AS SELECT * FROM src."INLFED";
