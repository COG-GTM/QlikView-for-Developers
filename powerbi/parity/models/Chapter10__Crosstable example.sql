-- Chapter10/Crosstable example.qvw
--   CrossTable(Month, Sales) LOAD Department, Jan, ..., Dec FROM [Crosstable example.xls] (biff, embedded labels, table is Sheet1$);
-- One qualifier column (Department); every other listed column becomes a (Month, Sales) row.
CREATE VIEW "Sheet1$" AS
SELECT Department, Month, Sales
FROM (
    UNPIVOT (SELECT Department, Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
             FROM read_parquet('{parquet}/Chapter10/Crosstable example/Sheet1.parquet'))
    ON Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec
    INTO NAME Month VALUE Sales
);
