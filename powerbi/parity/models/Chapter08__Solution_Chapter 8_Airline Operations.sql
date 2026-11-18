-- Source model for Chapter08/Solution_Chapter 8_Airline Operations.qvw, reproducing its load script
-- (inventory/scripts/Chapter08__Solution_Chapter 8_Airline Operations.qvs) independently of the Power Query.
--
-- Plain loads of Data Files/ (vFolderSourceData = ..\Data Files\), no WHERE Exists, no calendar, no Section Access.
-- [Aircraft Types] is the only transformed table: ApplyMap of the manufacturer country, LEFT JOIN of the engine
-- configuration, DROP FIELD of the join key and CONCATENATE of the 2010 update (378 rows = 369 + 9).
-- Origin / Destination Airports come from the repo's Dimension Tables.mdb (6,209 rows each); the .qvw was reloaded
-- from an older .mdb (2,104 / 2,169 rows), see inventory/row_count_exceptions.json.

-- [Main Data] (IF '$(vLoadMainData)' = 'Y', always 'Y'). Month is a dual: text plus Month__num.
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
FROM read_parquet('{parquet}/Data Files/QVDs/Flight Data.parquet');

CREATE VIEW "Carrier Groups" AS
SELECT "%Carrier Group ID", "Carrier Group" FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Groups.parquet');

CREATE VIEW "Airlines" AS
SELECT "%Airline ID", "Airline" FROM read_parquet('{parquet}/Data Files/QVDs/Airlines.parquet');

CREATE VIEW "Carrier Operating Region" AS
SELECT "%Region Code", "Carrier's Operating Region"
FROM read_parquet('{parquet}/Data Files/QVDs/Carrier Operating Region.parquet');

CREATE VIEW "Flight Types" AS
SELECT "%Datasource ID", "Flight Type" FROM read_parquet('{parquet}/Data Files/QVDs/Flight Types.parquet');

-- Map_Manufacturer_Country (schema src: mapping tables are not part of the data model). ApplyMap uses the first row
-- per Company.
CREATE SCHEMA src;
CREATE VIEW src.map_manufacturer_country AS
SELECT "Company", first("Country" ORDER BY rn) AS "Country"
FROM (SELECT *, row_number() OVER () AS rn FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Manufacturers.parquet'))
GROUP BY "Company";

CREATE VIEW "Aircraft Types" AS
SELECT b."AC_TYPEID"                                              AS "%Aircraft Type ID",
       b."SSD_NAME"                                               AS "Aircraft Name",
       b."MANUFACTURER"                                           AS "Aircraft Manufacturer",
       coalesce(mc."Country", 'Unknown')                          AS "Aircraft Manufacturer Country",
       b."LONG_NAME"                                              AS "Aircraft Name Full",
       b."SHORT_NAME"                                             AS "Aircraft Name Abbreviated",
       b."BEGIN_DATE"                                             AS "Aircraft Begin Date",
       b."END_DATE"                                               AS "Aircraft End Date",
       CASE WHEN year(b."BEGIN_DATE") < 1990 THEN 'Classic' ELSE 'Current' END AS "Aircraft Age Classification",
       g."Aircraft Engine Type",
       g."Aircraft Number Of Engines"
FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_Base_File.parquet') b
LEFT JOIN src.map_manufacturer_country mc ON mc."Company" = b."MANUFACTURER"
LEFT JOIN read_parquet('{parquet}/Data Files/CSVs/Aircraft_Group.parquet') g ON g."Aircraft Group ID" = b."AC_GROUP"
UNION ALL BY NAME
-- SubField(AC_GROUPNAME, ', ', n): null when the name has no n-th part ('Helicopter/Stol' has no engine count).
SELECT u."AC_TYPEID"                                              AS "%Aircraft Type ID",
       nullif(split_part(u."AC_GROUPNAME", ', ', 1), '')          AS "Aircraft Engine Type",
       nullif(split_part(u."AC_GROUPNAME", ', ', 2), '')          AS "Aircraft Number Of Engines",
       u."SSD_NAME"                                               AS "Aircraft Name",
       u."MANUFACTURER"                                           AS "Aircraft Manufacturer",
       coalesce(mc."Country", 'Unknown')                          AS "Aircraft Manufacturer Country",
       u."LONG_NAME"                                              AS "Aircraft Name Full",
       u."SHORT_NAME"                                             AS "Aircraft Name Abbreviated",
       u."BEGIN_DATE"                                             AS "Aircraft Begin Date",
       u."END_DATE"                                               AS "Aircraft End Date",
       'Current'                                                  AS "Aircraft Age Classification"
FROM read_parquet('{parquet}/Data Files/CSVs/Aircraft_2010_Update.parquet') u
LEFT JOIN src.map_manufacturer_country mc ON mc."Company" = u."MANUFACTURER";

CREATE VIEW "Distance Groups" AS
SELECT "%Distance Group ID", "Distance Interval" FROM read_parquet('{parquet}/Data Files/QVDs/Distance Groups.parquet');

CREATE VIEW "Origin Airports" AS
SELECT "%Origin Airport ID", "Origin Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Origin Airports.parquet');

CREATE VIEW "Destination Airports" AS
SELECT "%Destination Airport ID", "Destination Airport"
FROM read_parquet('{parquet}/Data Files/MDBs/Dimension Tables/Destination Airports.parquet');

CREATE VIEW "Origin Markets" AS
SELECT "%Origin Airport Market ID", "Origin Market" FROM read_parquet('{parquet}/Data Files/CSVs/Origin Markets.parquet');

CREATE VIEW "Destination Markets" AS
SELECT "%Destination Airport Market ID", "Destination Market"
FROM read_parquet('{parquet}/Data Files/CSVs/Destination Markets.parquet');
