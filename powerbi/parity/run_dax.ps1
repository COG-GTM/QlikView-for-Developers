<#
.SYNOPSIS
  Runs the parity harness's DAX queries against a Power BI semantic model and writes the
  results file that `harness.py compare` reads.

.DESCRIPTION
  Default target is the model of the .pbip currently open in Power BI Desktop on this
  Windows machine (Desktop hosts it in a local Analysis Services instance whose port is in
  msmdsrv.port.txt). Pass -Server/-Database to target any XMLA endpoint instead, e.g. a
  Premium/Fabric workspace: -Server "powerbi://api.powerbi.com/v1.0/myorg/<workspace>" -Database "<model>".

  Uses ADOMD.NET: the copy shipped with Power BI Desktop is found automatically; otherwise
  pass -AdomdPath to Microsoft.AnalysisServices.AdomdClient.dll (ADOMD.NET client / NuGet
  package Microsoft.AnalysisServices.AdomdClient.retail.amd64).

.EXAMPLE
  # 1) python powerbi/tools/convert_sources.py   (or download the CI "powerbi-parquet" artifact)
  # 2) open powerbi/apps/Chapter03_Airline_Operations/Chapter03_Airline_Operations.pbip, set DataRoot, Refresh
  # 3) python powerbi/parity/harness.py queries --app "Chapter03__Solution_Chapter 3_Airline Operations" --pbip powerbi/apps/Chapter03_Airline_Operations
  .\powerbi\parity\run_dax.ps1 -Queries "powerbi\parity\dax\Chapter03__Solution_Chapter 3_Airline Operations.queries.json" `
                               -Out "powerbi\parity\dax\Chapter03__Solution_Chapter 3_Airline Operations.results.json"
  # 4) python powerbi/parity/harness.py compare --app "Chapter03__Solution_Chapter 3_Airline Operations" --results "powerbi/parity/dax/Chapter03__Solution_Chapter 3_Airline Operations.results.json"
#>
param(
    [Parameter(Mandatory = $true)][string]$Queries,
    [Parameter(Mandatory = $true)][string]$Out,
    [string]$Server,
    [string]$Database,
    [string]$AdomdPath,
    [string]$Role
)
$ErrorActionPreference = 'Stop'

function Find-Adomd {
    if ($AdomdPath) { return $AdomdPath }
    $candidates = @(
        "$env:ProgramFiles\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll",
        "$env:ProgramFiles\Microsoft Power BI Desktop\bin\Microsoft.AnalysisServices.AdomdClient.dll"
    )
    $candidates += Get-ChildItem "$env:ProgramFiles\WindowsApps\Microsoft.MicrosoftPowerBIDesktop_*\bin\Microsoft.PowerBI.AdomdClient.dll" -ErrorAction SilentlyContinue | ForEach-Object FullName
    $candidates += Get-ChildItem "$env:WINDIR\Microsoft.NET\assembly\GAC_MSIL\Microsoft.AnalysisServices.AdomdClient\*\Microsoft.AnalysisServices.AdomdClient.dll" -ErrorAction SilentlyContinue | ForEach-Object FullName
    $hit = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if (-not $hit) { throw "ADOMD.NET not found. Install Power BI Desktop or the ADOMD.NET client, or pass -AdomdPath." }
    return $hit
}

function Find-DesktopServer {
    $roots = @(
        "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces",
        "$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces"
    )
    $portFiles = $roots | ForEach-Object { Get-ChildItem "$_\*\Data\msmdsrv.port.txt" -ErrorAction SilentlyContinue } |
        Sort-Object LastWriteTime -Descending
    if (-not $portFiles) { throw "No running Power BI Desktop model found. Open the app's .pbip and refresh it first." }
    $port = (Get-Content $portFiles[0].FullName -Encoding Unicode -Raw).Trim()
    return "localhost:$port"
}

Add-Type -Path (Find-Adomd)
if (-not $Server) { $Server = Find-DesktopServer }
$spec = Get-Content $Queries -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $Role -and $spec.PSObject.Properties['role'] -and $spec.role) { $Role = [string]$spec.role }
$connStr = "Data Source=$Server"
if ($Database) { $connStr += ";Initial Catalog=$Database" }
if ($Role) { $connStr += ";Roles=$Role" }
$conn = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection($connStr)
$conn.Open()
$results = New-Object System.Collections.Generic.List[object]
try {
    foreach ($q in @(@($spec.queries) + @($spec.relationships) | Where-Object { $_ })) {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = $q.query
        $reader = $cmd.ExecuteReader()
        $columns = @(for ($i = 0; $i -lt $reader.FieldCount; $i++) { $reader.GetName($i) })
        $rows = New-Object System.Collections.Generic.List[object]
        while ($reader.Read()) {
            $row = @(for ($i = 0; $i -lt $reader.FieldCount; $i++) {
                $v = $reader.GetValue($i)
                if ($v -is [System.DBNull]) { $null }
                elseif ($v -is [datetime]) { $v.ToString('yyyy-MM-ddTHH:mm:ss') }
                else { $v }
            })
            $rows.Add($row)
        }
        $reader.Close()
        $results.Add([ordered]@{ id = $q.id; columns = $columns; rows = $rows })
        Write-Host ("{0}: {1} rows" -f $q.id, $rows.Count)
    }
}
finally { $conn.Close() }

$doc = [ordered]@{
    app         = $spec.app
    produced_by = "run_dax.ps1 via ADOMD.NET on $env:COMPUTERNAME against $Server" + $(if ($Role) { " as role $Role" } else { "" })
    role        = $(if ($Role) { $Role } else { $null })
    executed_at = (Get-Date).ToUniversalTime().ToString('o')
    results     = $results
}
$doc | ConvertTo-Json -Depth 8 -Compress | Set-Content -Path $Out -Encoding UTF8
Write-Host "wrote $Out"
