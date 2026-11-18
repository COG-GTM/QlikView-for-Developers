-- Source model for Chapter09/Solution_Chapter 9_Link table.qvw, reproducing its load script
-- (inventory/scripts/Chapter09__Solution_Chapter 9_Link table.qvs) independently of the Power Query.
--
-- [Main Data] (flights) and [Employment Statistics] share a composite [%Key Field] (Period | Airline | Unique
-- Carrier | Carrier Group). [Link Table] holds the distinct key + calendar/carrier fields of both facts, and the
-- script then drops those fields from the facts, so they associate only through the link table. The link table is
-- not unique on [%Key Field]: five keys carry two Carrier Codes (ADB / AUQ), as in the .qvw (10,073 rows, 10,068 keys).

-- Qlik's & treats null as an empty string.
CREATE MACRO key_field(p, a, u, g) AS
    concat(coalesce(CAST(p AS VARCHAR), ''), ' | ', coalesce(CAST(a AS VARCHAR), ''), ' | ',
           coalesce(CAST(u AS VARCHAR), ''), ' | ', coalesce(CAST(g AS VARCHAR), ''));

CREATE SCHEMA src;

CREATE VIEW src.flight AS
SELECT key_field("Period", "%Airline ID", "%Unique Carrier Code", "%Carrier Group ID") AS "%Key Field", *
FROM read_parquet('{parquet}/Data Files/QVDs/Flight Data.parquet');

CREATE VIEW src.employment AS
SELECT key_field("Period", "%Airline ID", "%Unique Carrier Code", "%Carrier Group ID") AS "%Key Field", *
FROM read_parquet('{parquet}/Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet');

CREATE VIEW "Main Data" AS
SELECT "%Key Field", "%Unique Carrier Entity Code", "%Region Code",
       "%Origin Airport ID", "%Origin Airport Sequence ID", "%Origin Airport Market ID", "%Origin World Area Code",
       "%Destination Airport ID", "%Destination Airport Sequence ID", "%Destination Airport Market ID",
       "%Destination World Area Code", "%Aircraft Group ID", "%Aircraft Type ID", "%Aircraft Configuration ID",
       "%Distance Group ID", "%Service Class ID", "%Datasource ID",
       "# Departures Scheduled", "# Departures Performed", "# Payload", "Distance", "# Available Seats",
       "# Transported Passengers", "# Transported Freight", "# Transported Mail", "# Ramp-To-Ramp Time", "# Air Time",
       "Origin Airport Code", "Origin City", "Origin State Code", "Origin State FIPS", "Origin State",
       "Origin Country Code", "Origin Country",
       "Destination Airport Code", "Destination City", "Destination State Code", "Destination State FIPS",
       "Destination State", "Destination Country Code", "Destination Country",
       "From - To Airport Code", "From - To Airport ID", "From - To City", "From - To State Code", "From - To State"
FROM src.flight;

CREATE VIEW "Employment Statistics" AS
SELECT "%Key Field", "# Full Time Employees", "# Part Time Employees", "# Total Employees", "# Equivalent FTEs"
FROM src.employment;

-- Load Distinct from [Main Data], then Concatenate the employment keys Not Exists([%TEMP Key Field]) (the flight keys).
CREATE VIEW "Link Table" AS
WITH f AS (
    SELECT DISTINCT "%Key Field", "Year", "Period", "Month (#)", "Month", "Month__num", "Quarter", "%Airline ID",
           "%Unique Carrier Code", "%Carrier Group ID", "Unique Carrier", "Carrier Code", "Carrier Name"
    FROM src.flight
)
SELECT * FROM f
UNION ALL
SELECT DISTINCT "%Key Field", "Year", "Period", "Month (#)", "Month", "Month__num",
       'Q' || CAST(ceil("Month (#)" / 3.0) AS INTEGER) AS "Quarter", "%Airline ID",
       "%Unique Carrier Code", "%Carrier Group ID", "Unique Carrier", "Carrier Code", "Carrier Name"
FROM src.employment
WHERE "%Key Field" NOT IN (SELECT "%Key Field" FROM f);

-- Dimensions: WHERE Exists(<key>) against the values loaded so far (the carrier keys now live only in [Link Table]);
-- 'Unknown' members for missing keys. NOT Exists(Temp, key) is also true for a null key, so a null-key 'Unknown'
-- row is added when the resident table has null keys.
CREATE VIEW "Carrier Groups" AS
WITH s AS (
    SELECT "%Carrier Group ID", "Carrier Group" FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Groups.parquet')
    WHERE "%Carrier Group ID" IN (SELECT "%Carrier Group ID" FROM "Link Table")
)
SELECT * FROM s
UNION ALL
SELECT DISTINCT "%Carrier Group ID", 'Unknown' FROM "Link Table"
WHERE "%Carrier Group ID" IS NULL OR "%Carrier Group ID" NOT IN (SELECT "%Carrier Group ID" FROM s);

CREATE VIEW "Airlines" AS
SELECT "%Airline ID", "Airline" FROM read_parquet('{parquet}/Data Files/QVDs/Airlines.parquet')
WHERE "%Airline ID" IN (SELECT "%Airline ID" FROM "Link Table");

CREATE VIEW "Carrier Operating Region" AS
WITH s AS (
    SELECT "%Region Code", "Carrier's Operating Region"
    FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Operating Region.parquet')
    WHERE "%Region Code" IN (SELECT "%Region Code" FROM "Main Data")
)
SELECT * FROM s
UNION ALL
SELECT DISTINCT "%Region Code", 'Unknown' FROM "Main Data"
WHERE "%Region Code" IS NULL OR "%Region Code" NOT IN (SELECT "%Region Code" FROM s);

CREATE VIEW "Flight Types" AS
SELECT "%Datasource ID", "Flight Type" FROM read_parquet('{parquet}/Data Files/QVDs/Flight Types.parquet')
WHERE "%Datasource ID" IN (SELECT "%Datasource ID" FROM "Main Data");

-- [Aircraft Types]: Aircraft_Base_File.csv (ApplyMap manufacturer country, Classic before 1990), LEFT JOIN the
-- engine configuration from Aircraft_Group.csv, CONCATENATE Aircraft_2010_Update.csv (configuration split from
-- AC_GROUPNAME). Both loads keep Exists([%Aircraft Type ID], AC_TYPEID). QlikView trims unquoted delimited text
-- (Aircraft_Group.csv has " 4-Engine"; the stored Aircraft Types Transformed.qvd has "4-Engine"). STORE is not reproduced.
CREATE VIEW "Aircraft Types" AS
WITH mfr AS (
    SELECT "Company", first("Country") AS "Country"
    FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Manufacturers.parquet') GROUP BY "Company"
), used AS (
    SELECT DISTINCT "%Aircraft Type ID" FROM "Main Data"
)
SELECT b.AC_TYPEID AS "%Aircraft Type ID", b.SSD_NAME AS "Aircraft Name", b.MANUFACTURER AS "Aircraft Manufacturer",
       coalesce(mfr."Country", 'Unknown') AS "Aircraft Manufacturer Country", b.LONG_NAME AS "Aircraft Name Full",
       b.SHORT_NAME AS "Aircraft Name Abbreviated", b.BEGIN_DATE AS "Aircraft Begin Date",
       b.END_DATE AS "Aircraft End Date",
       CASE WHEN year(b.BEGIN_DATE) < 1990 THEN 'Classic' ELSE 'Current' END AS "Aircraft Age Classification",
       trim(g."Aircraft Engine Type") AS "Aircraft Engine Type",
       trim(g."Aircraft Number Of Engines") AS "Aircraft Number Of Engines"
FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Base_File.parquet') b
LEFT JOIN mfr ON mfr."Company" = b.MANUFACTURER
LEFT JOIN read_parquet('{parquet}/Data Files/CSVs/Aircraft_Group.parquet') g ON g."Aircraft Group ID" = b.AC_GROUP
WHERE b.AC_TYPEID IN (SELECT * FROM used)
UNION ALL
SELECT u.AC_TYPEID, u.SSD_NAME, u.MANUFACTURER, coalesce(mfr."Country", 'Unknown'), u.LONG_NAME, u.SHORT_NAME,
       u.BEGIN_DATE, u.END_DATE, 'Current',
       nullif(split_part(u.AC_GROUPNAME, ', ', 1), ''), nullif(split_part(u.AC_GROUPNAME, ', ', 2), '')
FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_2010_Update.parquet') u
LEFT JOIN mfr ON mfr."Company" = u.MANUFACTURER
WHERE u.AC_TYPEID IN (SELECT * FROM used);

CREATE VIEW "Distance Groups" AS
SELECT "%Distance Group ID", "Distance Interval" FROM read_parquet('{parquet}/Data Files/QVDs/Distance Groups.parquet')
WHERE "%Distance Group ID" IN (SELECT "%Distance Group ID" FROM "Main Data");

-- Left Keep ([Main Data]) from Dimension Tables.mdb.
CREATE VIEW "Origin Airports" AS
SELECT "%Origin Airport ID", "Origin Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Origin Airports.parquet')
WHERE "%Origin Airport ID" IN (SELECT "%Origin Airport ID" FROM "Main Data");

CREATE VIEW "Destination Airports" AS
SELECT "%Destination Airport ID", "Destination Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Destination Airports.parquet')
WHERE "%Destination Airport ID" IN (SELECT "%Destination Airport ID" FROM "Main Data");

CREATE VIEW "Origin Markets" AS
WITH s AS (
    SELECT "%Origin Airport Market ID", "Origin Market"
    FROM read_parquet('{parquet}/Data Files/CSVs/Origin Markets.parquet')
    WHERE "%Origin Airport Market ID" IN (SELECT "%Origin Airport Market ID" FROM "Main Data")
)
SELECT * FROM s
UNION ALL
SELECT DISTINCT "%Origin Airport Market ID", 'Unknown' FROM "Main Data"
WHERE "%Origin Airport Market ID" IS NULL
   OR "%Origin Airport Market ID" NOT IN (SELECT "%Origin Airport Market ID" FROM s);

CREATE VIEW "Destination Markets" AS
WITH s AS (
    SELECT "%Destination Airport Market ID", "Destination Market"
    FROM read_parquet('{parquet}/Data Files/CSVs/Destination Markets.parquet')
    WHERE "%Destination Airport Market ID" IN (SELECT "%Destination Airport Market ID" FROM "Main Data")
)
SELECT * FROM s
UNION ALL
SELECT DISTINCT "%Destination Airport Market ID", 'Unknown' FROM "Main Data"
WHERE "%Destination Airport Market ID" IS NULL
   OR "%Destination Airport Market ID" NOT IN (SELECT "%Destination Airport Market ID" FROM s);
