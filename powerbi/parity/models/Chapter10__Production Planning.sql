-- Chapter10/Production Planning.qvw, tab Main:
--   LOAD Date, [Plant #], [Product Line ID], [Estimated Production]
--   FROM [Production Planning - Legacy.txt] (txt, codepage is 1252, embedded labels, delimiter is '\t', msq, filters(...));
-- Each CTE is one QlikView transformation step, applied in script order to the raw cell grid
-- (rows numbered from 1 as in Pos(Top, n)). Written independently of the Power Query.
CREATE VIEW "Production Planning - Legacy" AS
WITH raw AS (
    SELECT row_number() OVER () AS n, *
    FROM read_csv('{repo}/Chapter10/Production Planning - Legacy.txt', delim = '\t', header = false,
                  auto_detect = false, null_padding = true, encoding = 'latin-1',
                  columns = {'c1': 'VARCHAR', 'c2': 'VARCHAR', 'c3': 'VARCHAR', 'c4': 'VARCHAR',
                             'c5': 'VARCHAR', 'c6': 'VARCHAR', 'c7': 'VARCHAR', 'c8': 'VARCHAR'})
),
-- Remove(Row, Pos(Top, 6)), then Pos(Top, 4), 3, 2, 1: the underline row and the report banner
body AS (SELECT * FROM raw WHERE n NOT IN (1, 2, 3, 4, 6)),
-- Remove(Row, RowCnd(CellValue, 1, StrCnd(contain, 'Total'))): weekly subtotal rows
no_totals AS (SELECT * FROM body WHERE coalesce(c1, '') NOT LIKE '%Total%'),
-- Unwrap(Col, Pos(Top, 5)): columns 5..8 continue below columns 1..4
unwrapped AS (
    SELECT 0 AS part, n, c1 AS a, c2 AS b, c3 AS c, c4 AS d FROM no_totals
    UNION ALL
    SELECT 1 AS part, n, c5, c6, c7, c8 FROM no_totals
),
ordered AS (SELECT row_number() OVER (ORDER BY part, n) AS r, a, b, c, d FROM unwrapped),
-- Remove(Row, RowCnd(Compound, contain 'Date', Interval(Pos(Top, 2), Pos(Bottom, 1)))): the second header
no_headers AS (SELECT * FROM ordered WHERE NOT (r >= 2 AND coalesce(a, '') LIKE '%Date%')),
-- Replace(1, top, StrCnd(null)): an empty Date cell takes the value above it
filled AS (
    SELECT r, last_value(nullif(a, '') IGNORE NULLS) OVER (ORDER BY r ROWS UNBOUNDED PRECEDING) AS a, b, c, d
    FROM no_headers
)
-- embedded labels: the first remaining row holds the field names; numbers as numbers, Product Line ID kept as its text label ("03")
SELECT CAST(a AS BIGINT) AS "Date", CAST(b AS BIGINT) AS "Plant #",
       c AS "Product Line ID", CAST(d AS BIGINT) AS "Estimated Production"
FROM filled
WHERE r > 1;
