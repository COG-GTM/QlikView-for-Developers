-- Chapter10/Hierarchy example.qvw:
--   HIERARCHY(Child_ID, Parent_ID, Child, ParentName, Child, Path, ' - ', HierarchyLevel)
--   LOAD Parent_ID, Child_ID, Parent, Child FROM [Hierarchy example.xls] (biff, embedded labels, table is Sheet1$);
-- Qlik expands the adjacency list into one row per node with the ancestors' names in
-- Child1..ChildN (root first, NULL below the node's own level), ParentName (the parent
-- node's name), Path (names root..node joined by ' - ') and the node's depth. The .qvw was
-- last reloaded before the depth field was renamed in the script, so its data model (and
-- table box TB01) has the field as Depth, not HierarchyLevel; we follow the data model.
CREATE VIEW "Sheet1$-ExpandedNodes" AS
WITH RECURSIVE src AS (
    SELECT CAST(Parent_ID AS BIGINT) AS Parent_ID, CAST(Child_ID AS BIGINT) AS Child_ID, Parent, Child
    FROM read_parquet('{parquet}/Chapter10/Hierarchy example/Sheet1.parquet')
),
walk AS (
    SELECT Child_ID AS node, Parent_ID AS ancestor, 1 AS up FROM src
    UNION ALL
    SELECT w.node, s.Parent_ID, w.up + 1 FROM walk w JOIN src s ON s.Child_ID = w.ancestor
    WHERE w.ancestor IS NOT NULL
),
depth AS (
    SELECT node, max(up) AS Depth FROM walk GROUP BY node
),
lineage AS (  -- (node, level, name) for every ancestor and the node itself, level 1 = root
    SELECT d.node, d.Depth - w.up AS level, s.Child AS name
    FROM walk w JOIN depth d ON d.node = w.node JOIN src s ON s.Child_ID = w.ancestor
    UNION ALL
    SELECT d.node, d.Depth AS level, s.Child FROM depth d JOIN src s ON s.Child_ID = d.node
)
SELECT s.Parent_ID, s.Child_ID, s.Parent, s.Child,
       max(CASE WHEN l.level = 1 THEN l.name END) AS Child1,
       max(CASE WHEN l.level = 2 THEN l.name END) AS Child2,
       max(CASE WHEN l.level = 3 THEN l.name END) AS Child3,
       max(CASE WHEN l.level = 4 THEN l.name END) AS Child4,
       p.Child AS ParentName,
       string_agg(l.name, ' - ' ORDER BY l.level) AS Path,
       d.Depth
FROM src s
JOIN depth d ON d.node = s.Child_ID
JOIN lineage l ON l.node = s.Child_ID
LEFT JOIN src p ON p.Child_ID = s.Parent_ID
GROUP BY s.Parent_ID, s.Child_ID, s.Parent, s.Child, p.Child, d.Depth;
