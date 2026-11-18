-- Source model for Chapter15/Solution_Chapter 15_Airline Operations.qvw, reproducing its load script
-- (inventory/scripts/Chapter15__Solution_Chapter 15_Airline Operations.qvs) independently of the Power Query.
--
-- Everything the script loads is built in schema `src`. The views the harness reads (schema main) then apply the
-- hidden script's Section Access reduction: QlikView keeps only rows associated with the user's %FLIGHTTYPE values
-- ('*' = every value listed in the Section Access table) and drops all rows not associated with them, including the
-- [Main Data] rows from Employment Statistics, which have no %Datasource ID. This applies to ADMIN too: the .qvw's
-- stored row counts (Main Data 1,256,075; Airlines 336; Carrier Operating Region 7; Origin / Destination Markets
-- 1,859 / 1,917) are exactly the ADMIN-reduced counts, while Chapters 13-14 (same script, no Section Access) store
-- the unreduced 1,258,763 / 337 / 8 / 1,860 / 1,918. src.current_user picks whose view main shows (default ADMIN).

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

-- Inline tables. INLFED-1 is the metric picker; INLFED is loaded after Section Access and maps the reduction
-- field %FLIGHTTYPE onto Flight Type.
CREATE VIEW src."INLFED-1" AS
SELECT * FROM (VALUES ('# of Flights', 'eDeparturesPerformed'), ('Enplaned Passengers', 'eEnplanedPassengers'),
                      ('Air Time', 'eAirTime')) AS t("Metric Name", "eMetric");

CREATE VIEW src."INLFED" AS
SELECT * FROM (VALUES ('Domestic, Foreign Carriers', 'DOMESTIC_FOREIGN'),
                      ('Domestic, US Carriers Only', 'DOMESTIC_US'),
                      ('International, Foreign Carriers', 'INTERNATIONAL_FOREIGN'),
                      ('International, US Carriers Only', 'INTERNATIONAL_US')) AS t("Flight Type", "%FLIGHTTYPE");


-- Section Access (passwords are not part of the model; Power BI authenticates users itself).
CREATE TABLE src."Section Access" AS
SELECT * FROM (VALUES ('ADMIN', 'ADMIN', '*', NULL), ('ADMIN', 'ADMIN', 'INTERNATIONAL_US', NULL),
                      ('USER', 'DF', 'DOMESTIC_FOREIGN', NULL), ('USER', 'DU', 'DOMESTIC_US', NULL),
                      ('USER', 'IF', 'INTERNATIONAL_FOREIGN', NULL), ('USER', 'NOCARRIER', '*', 'Carrier Name'))
    AS t("ACCESS", "USERID", "%FLIGHTTYPE", "OMIT");

CREATE TABLE src.current_user AS SELECT 'ADMIN' AS "USERID";

CREATE VIEW src.allowed_flight_types AS
SELECT DISTINCT v."%FLIGHTTYPE"
FROM src."Section Access" a JOIN src.current_user u USING ("USERID")
JOIN (SELECT DISTINCT "%FLIGHTTYPE" FROM src."Section Access" WHERE "%FLIGHTTYPE" <> '*') v
  ON a."%FLIGHTTYPE" IN ('*', v."%FLIGHTTYPE");

-- Dimension rows survive when a surviving [Main Data] row carries their key; a null-key 'Unknown' row survives when
-- surviving [Main Data] rows have a null key too (Carrier Groups: 12 flight rows without a carrier group).
CREATE VIEW "INLFED" AS
SELECT * FROM src."INLFED" WHERE "%FLIGHTTYPE" IN (SELECT "%FLIGHTTYPE" FROM src.allowed_flight_types);
CREATE VIEW "Flight Types" AS
SELECT * FROM src."Flight Types" WHERE "Flight Type" IN (SELECT "Flight Type" FROM "INLFED");
CREATE VIEW "Main Data" AS
SELECT * FROM src."Main Data" WHERE "%Datasource ID" IN (SELECT "%Datasource ID" FROM "Flight Types");
CREATE VIEW "Master Calendar" AS
SELECT * FROM src."Master Calendar" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."Period" IS NOT DISTINCT FROM d."Period");
CREATE VIEW "Carrier Groups" AS
SELECT * FROM src."Carrier Groups" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Carrier Group ID" IS NOT DISTINCT FROM d."%Carrier Group ID");
CREATE VIEW "Airlines" AS
SELECT * FROM src."Airlines" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Airline ID" IS NOT DISTINCT FROM d."%Airline ID");
CREATE VIEW "Carrier Operating Region" AS
SELECT * FROM src."Carrier Operating Region" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Region Code" IS NOT DISTINCT FROM d."%Region Code");
CREATE VIEW "Aircraft Types" AS
SELECT * FROM src."Aircraft Types" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Aircraft Type ID" IS NOT DISTINCT FROM d."%Aircraft Type ID");
CREATE VIEW "Distance Groups" AS
SELECT * FROM src."Distance Groups" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Distance Group ID" IS NOT DISTINCT FROM d."%Distance Group ID");
CREATE VIEW "Origin Airports" AS
SELECT * FROM src."Origin Airports" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Origin Airport ID" IS NOT DISTINCT FROM d."%Origin Airport ID");
CREATE VIEW "Destination Airports" AS
SELECT * FROM src."Destination Airports" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Destination Airport ID" IS NOT DISTINCT FROM d."%Destination Airport ID");
CREATE VIEW "Origin Markets" AS
SELECT * FROM src."Origin Markets" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Origin Airport Market ID" IS NOT DISTINCT FROM d."%Origin Airport Market ID");
CREATE VIEW "Destination Markets" AS
SELECT * FROM src."Destination Markets" d
WHERE EXISTS (SELECT 1 FROM "Main Data" f WHERE f."%Destination Airport Market ID" IS NOT DISTINCT FROM d."%Destination Airport Market ID");
CREATE VIEW "INLFED-1" AS SELECT * FROM src."INLFED-1";
