-- Source model for Chapter12/Solution_Chapter 12_Airline Operations.qvw, reproducing its load script
-- (inventory/scripts/Chapter12__Solution_Chapter 12_Airline Operations.qvs) independently of the Power Query.
-- No Section Access: the .qvw's stored row counts are the unreduced ones (Main Data 1,258,763; Airlines 337).

-- [Main Data]: Data Files\QVDs\Flight Data.qvd, then Concatenate T_F41SCHEDULE_P1A_EMP.qvd.
CREATE VIEW "Main Data" AS
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
       NULL::BIGINT AS "# Full Time Employees", NULL::BIGINT AS "# Part Time Employees",
       NULL::BIGINT AS "# Total Employees", NULL::BIGINT AS "# Equivalent FTEs"
FROM read_parquet('{parquet}/Data Files/QVDs/Flight Data.parquet')
UNION ALL BY NAME
SELECT "%Airline ID", "%Unique Carrier Code", "%Carrier Group ID", "# Full Time Employees", "# Part Time Employees",
       "# Total Employees", "# Equivalent FTEs", "Unique Carrier", "Carrier Code", "Carrier Name", "Period"
FROM read_parquet('{parquet}/Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet');

-- [Master Calendar]: one row per *day* from MonthStart(min Period) to MonthStart(max Period) (1065 rows; the
-- LOAD DISTINCTs sit under a non-distinct preceding `Load *`).
CREATE VIEW "Master Calendar" AS
WITH rng AS (
    SELECT strptime(CAST(min("Period") AS VARCHAR), '%Y%m')::DATE AS lo,
           strptime(CAST(max("Period") AS VARCHAR), '%Y%m')::DATE AS hi
    FROM "Main Data"
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

-- Dimension tables: WHERE Exists(<key>) against [Main Data]; Carrier Groups, Carrier Operating Region and the
-- markets then concatenate an 'Unknown' member for every [Main Data] key value missing from the dimension
-- (NOT Exists(Temp, key) is also true for a null key).
CREATE VIEW "Carrier Groups" AS
WITH d AS (
    SELECT "%Carrier Group ID", "Carrier Group" FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Groups.parquet')
    WHERE "%Carrier Group ID" IN (SELECT "%Carrier Group ID" FROM "Main Data")
)
SELECT * FROM d
UNION ALL
SELECT DISTINCT "%Carrier Group ID", 'Unknown' FROM "Main Data"
WHERE "%Carrier Group ID" IS NULL OR "%Carrier Group ID" NOT IN (SELECT "%Carrier Group ID" FROM d);

CREATE VIEW "Airlines" AS
SELECT "%Airline ID", "Airline" FROM read_parquet('{parquet}/Data Files/QVDs/Airlines.parquet')
WHERE "%Airline ID" IN (SELECT "%Airline ID" FROM "Main Data");

CREATE VIEW "Carrier Operating Region" AS
WITH d AS (
    SELECT "%Region Code", "Carrier's Operating Region"
    FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Operating Region.parquet')
    WHERE "%Region Code" IN (SELECT "%Region Code" FROM "Main Data")
)
SELECT * FROM d
UNION ALL
SELECT DISTINCT "%Region Code", 'Unknown' FROM "Main Data"
WHERE "%Region Code" IS NULL OR "%Region Code" NOT IN (SELECT "%Region Code" FROM d);

CREATE VIEW "Flight Types" AS
SELECT "%Datasource ID", "Flight Type" FROM read_parquet('{parquet}/Data Files/QVDs/Flight Types.parquet')
WHERE "%Datasource ID" IN (SELECT "%Datasource ID" FROM "Main Data");

-- [Aircraft Types]: Aircraft_Base_File.csv WHERE Exists, ApplyMap(Map_Manufacturer_Country, MANUFACTURER, 'Unknown'),
-- LEFT JOIN Aircraft_Group.csv on the group key, then Concatenate Aircraft_2010_Update.csv WHERE Exists.
-- Qlik trims unquoted text-file fields and loads an empty one as '' (the Parquet export has NULL).
CREATE VIEW "Aircraft Types" AS
WITH keys AS (SELECT DISTINCT "%Aircraft Type ID" AS k FROM "Main Data"),
map AS (SELECT "Company", "Country" FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Manufacturers.parquet')),
grp AS (
    SELECT "Aircraft Group ID", trim("Aircraft Engine Type") AS "Aircraft Engine Type",
           trim("Aircraft Number Of Engines") AS "Aircraft Number Of Engines"
    FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Group.parquet')
), base AS (
    SELECT b.AC_TYPEID, b.SSD_NAME, coalesce(b.MANUFACTURER, '') AS MANUFACTURER, b.LONG_NAME, b.SHORT_NAME,
           b.BEGIN_DATE, b.END_DATE, CASE WHEN year(b.BEGIN_DATE) < 1990 THEN 'Classic' ELSE 'Current' END AS age,
           g."Aircraft Engine Type" AS engine, g."Aircraft Number Of Engines" AS engines
    FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Base_File.parquet') b
    LEFT JOIN grp g ON g."Aircraft Group ID" = b.AC_GROUP
    WHERE b.AC_TYPEID IN (SELECT k FROM keys)
), upd AS (
    SELECT AC_TYPEID, SSD_NAME, coalesce(MANUFACTURER, '') AS MANUFACTURER, LONG_NAME, SHORT_NAME, BEGIN_DATE,
           END_DATE, 'Current' AS age, nullif(split_part(AC_GROUPNAME, ', ', 1), '') AS engine,
           nullif(split_part(AC_GROUPNAME, ', ', 2), '') AS engines
    FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_2010_Update.parquet')
    WHERE AC_TYPEID IN (SELECT k FROM keys)
), aircraft AS (SELECT * FROM base UNION ALL SELECT * FROM upd)
SELECT a.AC_TYPEID AS "%Aircraft Type ID", a.SSD_NAME AS "Aircraft Name", a.MANUFACTURER AS "Aircraft Manufacturer",
       coalesce(map."Country", 'Unknown') AS "Aircraft Manufacturer Country", a.LONG_NAME AS "Aircraft Name Full",
       a.SHORT_NAME AS "Aircraft Name Abbreviated", a.BEGIN_DATE AS "Aircraft Begin Date",
       a.END_DATE AS "Aircraft End Date", a.age AS "Aircraft Age Classification", a.engine AS "Aircraft Engine Type",
       a.engines AS "Aircraft Number Of Engines"
FROM aircraft a LEFT JOIN map ON map."Company" = a.MANUFACTURER;

CREATE VIEW "Distance Groups" AS
SELECT "%Distance Group ID", "Distance Interval" FROM read_parquet('{parquet}/Data Files/QVDs/Distance Groups.parquet')
WHERE "%Distance Group ID" IN (SELECT "%Distance Group ID" FROM "Main Data");

-- Airports: SQL SELECT * FROM Dimension Tables.mdb with LEFT KEEP ([Main Data]).
CREATE VIEW "Origin Airports" AS
SELECT "%Origin Airport ID", "Origin Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Origin Airports.parquet')
WHERE "%Origin Airport ID" IN (SELECT "%Origin Airport ID" FROM "Main Data");

CREATE VIEW "Destination Airports" AS
SELECT "%Destination Airport ID", "Destination Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Destination Airports.parquet')
WHERE "%Destination Airport ID" IN (SELECT "%Destination Airport ID" FROM "Main Data");

-- Markets: tab-delimited CSVs WHERE Exists + 'Unknown' members.
CREATE VIEW "Origin Markets" AS
WITH d AS (
    SELECT "%Origin Airport Market ID", "Origin Market"
    FROM read_parquet('{parquet}/Data Files/CSVs/Origin Markets.parquet')
    WHERE "%Origin Airport Market ID" IN (SELECT "%Origin Airport Market ID" FROM "Main Data")
)
SELECT * FROM d
UNION ALL
SELECT DISTINCT "%Origin Airport Market ID", 'Unknown' FROM "Main Data"
WHERE "%Origin Airport Market ID" IS NULL
   OR "%Origin Airport Market ID" NOT IN (SELECT "%Origin Airport Market ID" FROM d);

CREATE VIEW "Destination Markets" AS
WITH d AS (
    SELECT "%Destination Airport Market ID", "Destination Market"
    FROM read_parquet('{parquet}/Data Files/CSVs/Destination Markets.parquet')
    WHERE "%Destination Airport Market ID" IN (SELECT "%Destination Airport Market ID" FROM "Main Data")
)
SELECT * FROM d
UNION ALL
SELECT DISTINCT "%Destination Airport Market ID", 'Unknown' FROM "Main Data"
WHERE "%Destination Airport Market ID" IS NULL
   OR "%Destination Airport Market ID" NOT IN (SELECT "%Destination Airport Market ID" FROM d);

-- Metric picker inline table.
CREATE VIEW "INLFED" AS
SELECT * FROM (VALUES ('# of Flights', 'eDeparturesPerformed'), ('Enplaned Passengers', 'eEnplanedPassengers'),
                      ('Air Time', 'eAirTime')) AS t("Metric Name", "eMetric");
