-- Chapter10/Generic Load.qvw
--   GENERIC LOAD Object, Attribute, Value FROM [Generic DB.xlsx] (ooxml, embedded labels, table is GenericDB);
-- QlikView creates one table per distinct Attribute, named GenericDB.<Attribute>, holding the
-- key (Object) and a field named after the attribute with the row's Value. All of them share
-- the Object key. Excel numbers are read as numbers by Qlik, so the Value attribute is numeric.
CREATE VIEW "GenericDB.Color" AS
  SELECT "Object", "Value" AS "Color" FROM read_parquet('{parquet}/Chapter10/Generic DB/GenericDB.parquet')
  WHERE "Attribute" = 'Color';
CREATE VIEW "GenericDB.Weight" AS
  SELECT "Object", "Value" AS "Weight" FROM read_parquet('{parquet}/Chapter10/Generic DB/GenericDB.parquet')
  WHERE "Attribute" = 'Weight';
CREATE VIEW "GenericDB.Diameter" AS
  SELECT "Object", "Value" AS "Diameter" FROM read_parquet('{parquet}/Chapter10/Generic DB/GenericDB.parquet')
  WHERE "Attribute" = 'Diameter';
CREATE VIEW "GenericDB.Value" AS
  SELECT "Object", CAST("Value" AS BIGINT) AS "Value" FROM read_parquet('{parquet}/Chapter10/Generic DB/GenericDB.parquet')
  WHERE "Attribute" = 'Value';
CREATE VIEW "GenericDB.Thickness" AS
  SELECT "Object", "Value" AS "Thickness" FROM read_parquet('{parquet}/Chapter10/Generic DB/GenericDB.parquet')
  WHERE "Attribute" = 'Thickness';
