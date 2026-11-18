-- Source model for Chapter09/Solution_Chapter 9_Airline Operations.qvw, reproducing its load script
-- (inventory/scripts/Chapter09__Solution_Chapter 9_Airline Operations.qvs) independently of the Power Query.
-- No Section Access: the views are the full model as the script loads it (Main Data 1,258,763 rows).

-- [Main Data]: Data Files\QVDs\Flight Data.qvd, then Concatenate T_F41SCHEDULE_P1A_EMP.qvd (Year / Quarter /
-- Month (#) / Month are commented out in both loads).
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

-- [Master Calendar]: MonthStart of every day from min(Period) to max(Period); both loads are DISTINCT (unlike
-- Chapter 15, which adds a non-distinct preceding Load *), so one row per month (36).
CREATE VIEW "Master Calendar" AS
WITH rng AS (
    SELECT strptime(CAST(min("Period") AS VARCHAR), '%Y%m')::DATE AS lo,
           strptime(CAST(max("Period") AS VARCHAR), '%Y%m')::DATE AS hi
    FROM "Main Data"
), months AS (
    SELECT DISTINCT date_trunc('month', d)::DATE AS m
    FROM rng, generate_series(lo::TIMESTAMP, hi::TIMESTAMP, INTERVAL 1 DAY) AS g(d)
)
SELECT year(m) * 100 + month(m)                   AS "Period",
       year(m)                                    AS "Year",
       strftime(m, '%b')                          AS "Month",
       CAST(month(m) AS DOUBLE)                   AS "Month__num",
       strftime(m, '%Y-%m')                       AS "Year - Month",
       CAST(m - DATE '1899-12-30' AS DOUBLE)      AS "Year - Month__num",
       'Q' || CAST(ceil(month(m) / 3) AS INTEGER) AS "Quarter"
FROM months;

-- Dimension tables: WHERE Exists(<key>) / LEFT KEEP ([Main Data]) against the key values of [Main Data]; four of them
-- then concatenate an 'Unknown' member for every [Main Data] key value missing from the dimension. NOT Exists(Temp,
-- key) is also true for a null key, so Qlik adds a null-key 'Unknown' row when [Main Data] has null keys.
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

-- [Aircraft Types]: Aircraft_Base_File.csv (ApplyMap of the manufacturer's country, first match, default 'Unknown';
-- Classic before 1990), LEFT JOIN the engine configuration from Aircraft_Group.csv, then CONCATENATE the 2010 update
-- (engine type / number from SubField(AC_GROUPNAME, ', ')). Exists() on both loads checks the [Main Data] keys.
-- QlikView trims unquoted text fields of delimited files (Aircraft_Group.csv has ' 4-Engine'); the Parquet keeps them.
CREATE VIEW "Aircraft Types" AS
WITH manufacturer AS (
    SELECT "Company", first("Country" ORDER BY rn) AS "Country"
    FROM (SELECT *, row_number() OVER () AS rn FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Manufacturers.parquet'))
    GROUP BY "Company"
), base AS (
    SELECT b.*, row_number() OVER () AS rn
    FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Base_File.parquet') b
    WHERE b."AC_TYPEID" IN (SELECT "%Aircraft Type ID" FROM "Main Data")
), upd AS (
    SELECT u.* FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_2010_Update.parquet') u
    WHERE u."AC_TYPEID" IN (SELECT "%Aircraft Type ID" FROM "Main Data")
)
SELECT b."AC_TYPEID" AS "%Aircraft Type ID", b."SSD_NAME" AS "Aircraft Name", b."MANUFACTURER" AS "Aircraft Manufacturer",
       coalesce(m."Country", 'Unknown') AS "Aircraft Manufacturer Country", b."LONG_NAME" AS "Aircraft Name Full",
       b."SHORT_NAME" AS "Aircraft Name Abbreviated", b."BEGIN_DATE" AS "Aircraft Begin Date",
       b."END_DATE" AS "Aircraft End Date",
       CASE WHEN year(b."BEGIN_DATE") < 1990 THEN 'Classic' ELSE 'Current' END AS "Aircraft Age Classification",
       trim(g."Aircraft Engine Type") AS "Aircraft Engine Type",
       trim(g."Aircraft Number Of Engines") AS "Aircraft Number Of Engines"
FROM base b
LEFT JOIN manufacturer m ON m."Company" = b."MANUFACTURER"
LEFT JOIN read_parquet('{parquet}/Data Files/CSVs/Aircraft_Group.parquet') g ON g."Aircraft Group ID" = b."AC_GROUP"
UNION ALL
SELECT u."AC_TYPEID", u."SSD_NAME", u."MANUFACTURER", coalesce(m."Country", 'Unknown'), u."LONG_NAME", u."SHORT_NAME",
       u."BEGIN_DATE", u."END_DATE", 'Current',
       nullif(split_part(u."AC_GROUPNAME", ', ', 1), ''), nullif(split_part(u."AC_GROUPNAME", ', ', 2), '')
FROM upd u
LEFT JOIN manufacturer m ON m."Company" = u."MANUFACTURER";

CREATE VIEW "Distance Groups" AS
SELECT "%Distance Group ID", "Distance Interval" FROM read_parquet('{parquet}/Data Files/QVDs/Distance Groups.parquet')
WHERE "%Distance Group ID" IN (SELECT "%Distance Group ID" FROM "Main Data");

-- Airports come from Dimension Tables.mdb through LEFT KEEP ([Main Data]): only airports [Main Data] references.
CREATE VIEW "Origin Airports" AS
SELECT "%Origin Airport ID", "Origin Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Origin Airports.parquet')
WHERE "%Origin Airport ID" IN (SELECT "%Origin Airport ID" FROM "Main Data");

CREATE VIEW "Destination Airports" AS
SELECT "%Destination Airport ID", "Destination Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Destination Airports.parquet')
WHERE "%Destination Airport ID" IN (SELECT "%Destination Airport ID" FROM "Main Data");

CREATE VIEW "Origin Markets" AS
WITH d AS (
    SELECT "%Origin Airport Market ID", "Origin Market" FROM read_parquet('{parquet}/Data Files/CSVs/Origin Markets.parquet')
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
