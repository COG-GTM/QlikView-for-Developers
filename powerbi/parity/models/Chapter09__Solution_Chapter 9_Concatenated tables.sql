-- Source model for Chapter09/Solution_Chapter 9_Concatenated tables.qvw, reproducing its load script
-- (inventory/scripts/Chapter09__Solution_Chapter 9_Concatenated tables.qvs) independently of the Power Query.
-- vFolderSourceData (config.qvs, not in the repo) is the repo's Data Files folder; vLoadMainData = 'Y'.
-- No Section Access: the inventory row counts are the unreduced ones (Main Data 1,258,763).

-- [Main Data]: Flight Data.qvd, then Concatenate T_F41SCHEDULE_P1A_EMP.qvd with Quarter = 'Q' & Ceil([Month (#)]/3, 1).
-- Month is a dual (text + number); Month__num carries its number like the converted QVDs do.
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
       "Year", "Period", "Quarter", "Month (#)", "Month", "Month__num",
       "From - To Airport Code", "From - To Airport ID", "From - To City", "From - To State Code", "From - To State"
FROM read_parquet('{parquet}/Data Files/QVDs/Flight Data.parquet')
UNION ALL BY NAME
SELECT "%Airline ID", "%Unique Carrier Code", "%Carrier Group ID",
       "# Full Time Employees", "# Part Time Employees", "# Total Employees", "# Equivalent FTEs",
       "Unique Carrier", "Carrier Code", "Carrier Name", "Year",
       'Q' || CAST(ceil("Month (#)" / 3) AS BIGINT) AS "Quarter",
       "Period", "Month (#)", "Month", "Month__num"
FROM read_parquet('{parquet}/Data Files/QVDs/T_F41SCHEDULE_P1A_EMP.parquet');

-- WHERE Exists(key) dimensions, plus an 'Unknown' member for every [Main Data] key value missing from the dimension.
-- NOT Exists(Temp, key) is also true for a null key (the Employment rows have no region or market), so Qlik adds a
-- null-key 'Unknown' row there.
CREATE VIEW "Carrier Groups" AS
WITH kept AS (
    SELECT "%Carrier Group ID", "Carrier Group" FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Groups.parquet')
    WHERE "%Carrier Group ID" IN (SELECT "%Carrier Group ID" FROM "Main Data")
)
SELECT * FROM kept
UNION ALL
SELECT DISTINCT "%Carrier Group ID", 'Unknown' FROM "Main Data"
WHERE "%Carrier Group ID" IS NULL OR "%Carrier Group ID" NOT IN (SELECT "%Carrier Group ID" FROM kept);

CREATE VIEW "Airlines" AS
SELECT "%Airline ID", "Airline" FROM read_parquet('{parquet}/Data Files/QVDs/Airlines.parquet')
WHERE "%Airline ID" IN (SELECT "%Airline ID" FROM "Main Data");

CREATE VIEW "Carrier Operating Region" AS
WITH kept AS (
    SELECT "%Region Code", "Carrier's Operating Region"
    FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Operating Region.parquet')
    WHERE "%Region Code" IN (SELECT "%Region Code" FROM "Main Data")
)
SELECT * FROM kept
UNION ALL
SELECT DISTINCT "%Region Code", 'Unknown' FROM "Main Data"
WHERE "%Region Code" IS NULL OR "%Region Code" NOT IN (SELECT "%Region Code" FROM kept);

CREATE VIEW "Flight Types" AS
SELECT "%Datasource ID", "Flight Type" FROM read_parquet('{parquet}/Data Files/QVDs/Flight Types.parquet')
WHERE "%Datasource ID" IN (SELECT "%Datasource ID" FROM "Main Data");

-- [Aircraft Types]: Aircraft_Base_File.csv WHERE Exists, ApplyMap('Map_Manufacturer_Country', MANUFACTURER, 'Unknown')
-- (Aircraft_Manufacturers.csv), LEFT JOIN Aircraft_Group.csv on the group, DROP FIELD [%Aircraft Group Type], then
-- CONCATENATE Aircraft_2010_Update.csv with SubField(AC_GROUPNAME, ', ', 1|2). The STORE into
-- Aircraft Types Transformed.qvd is a file side effect and not part of the model.
CREATE VIEW "Aircraft Types" AS
WITH manufacturers AS (
    SELECT "Company", "Country" FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Manufacturers.parquet')
), base AS (
    SELECT b.AC_TYPEID AS "%Aircraft Type ID", b.SSD_NAME AS "Aircraft Name", b.MANUFACTURER AS "Aircraft Manufacturer",
           coalesce(mf."Country", 'Unknown') AS "Aircraft Manufacturer Country",
           b.LONG_NAME AS "Aircraft Name Full", b.SHORT_NAME AS "Aircraft Name Abbreviated",
           b.BEGIN_DATE AS "Aircraft Begin Date", b.END_DATE AS "Aircraft End Date",
           CASE WHEN year(b.BEGIN_DATE) < 1990 THEN 'Classic' ELSE 'Current' END AS "Aircraft Age Classification",
           g."Aircraft Engine Type", g."Aircraft Number Of Engines"
    FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Base_File.parquet') b
    LEFT JOIN manufacturers mf ON mf."Company" = b.MANUFACTURER
    LEFT JOIN read_parquet('{parquet}/Data Files/CSVs/Aircraft_Group.parquet') g ON g."Aircraft Group ID" = b.AC_GROUP
    WHERE b.AC_TYPEID IN (SELECT "%Aircraft Type ID" FROM "Main Data")
), upd AS (
    SELECT u.AC_TYPEID AS "%Aircraft Type ID", u.SSD_NAME AS "Aircraft Name", u.MANUFACTURER AS "Aircraft Manufacturer",
           coalesce(mf."Country", 'Unknown') AS "Aircraft Manufacturer Country",
           u.LONG_NAME AS "Aircraft Name Full", u.SHORT_NAME AS "Aircraft Name Abbreviated",
           u.BEGIN_DATE AS "Aircraft Begin Date", u.END_DATE AS "Aircraft End Date",
           'Current' AS "Aircraft Age Classification",
           string_split(u.AC_GROUPNAME, ', ')[1] AS "Aircraft Engine Type",
           string_split(u.AC_GROUPNAME, ', ')[2] AS "Aircraft Number Of Engines"
    FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_2010_Update.parquet') u
    LEFT JOIN manufacturers mf ON mf."Company" = u.MANUFACTURER
    WHERE u.AC_TYPEID IN (SELECT "%Aircraft Type ID" FROM "Main Data")
)
SELECT * FROM base
UNION ALL BY NAME
SELECT * FROM upd;

CREATE VIEW "Distance Groups" AS
SELECT "%Distance Group ID", "Distance Interval" FROM read_parquet('{parquet}/Data Files/QVDs/Distance Groups.parquet')
WHERE "%Distance Group ID" IN (SELECT "%Distance Group ID" FROM "Main Data");

-- Airports: SQL SELECT * from Dimension Tables.mdb, Left Keep ([Main Data]).
CREATE VIEW "Origin Airports" AS
SELECT "%Origin Airport ID", "Origin Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Origin Airports.parquet')
WHERE "%Origin Airport ID" IN (SELECT "%Origin Airport ID" FROM "Main Data");

CREATE VIEW "Destination Airports" AS
SELECT "%Destination Airport ID", "Destination Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Destination Airports.parquet')
WHERE "%Destination Airport ID" IN (SELECT "%Destination Airport ID" FROM "Main Data");

CREATE VIEW "Origin Markets" AS
WITH kept AS (
    SELECT "%Origin Airport Market ID", "Origin Market"
    FROM read_parquet('{parquet}/Data Files/CSVs/Origin Markets.parquet')
    WHERE "%Origin Airport Market ID" IN (SELECT "%Origin Airport Market ID" FROM "Main Data")
)
SELECT * FROM kept
UNION ALL
SELECT DISTINCT "%Origin Airport Market ID", 'Unknown' FROM "Main Data"
WHERE "%Origin Airport Market ID" IS NULL
   OR "%Origin Airport Market ID" NOT IN (SELECT "%Origin Airport Market ID" FROM kept);

CREATE VIEW "Destination Markets" AS
WITH kept AS (
    SELECT "%Destination Airport Market ID", "Destination Market"
    FROM read_parquet('{parquet}/Data Files/CSVs/Destination Markets.parquet')
    WHERE "%Destination Airport Market ID" IN (SELECT "%Destination Airport Market ID" FROM "Main Data")
)
SELECT * FROM kept
UNION ALL
SELECT DISTINCT "%Destination Airport Market ID", 'Unknown' FROM "Main Data"
WHERE "%Destination Airport Market ID" IS NULL
   OR "%Destination Airport Market ID" NOT IN (SELECT "%Destination Airport Market ID" FROM kept);
