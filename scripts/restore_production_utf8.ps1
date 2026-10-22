param(
  [Parameter(Mandatory = $true)]
  [string]$ExternalDatabaseUrl,
  [string]$DumpsRoot = "",
  [switch]$SkipPacks,
  [switch]$WhatIf
)

$ErrorActionPreference = "Stop"
$roots = @( @($DumpsRoot, "C:\Users\Hp23\dourbia_dumps", "E:\dourbia_dumps") |
  Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique )
if ($roots.Count -eq 0) { throw "Aucun dossier de dumps trouve (passer -DumpsRoot)" }

function Find-Dump([string]$rel) {
  foreach ($r in $roots) {
    $p = Join-Path $r $rel
    if (Test-Path $p) { return $p }
  }
  return (Join-Path $roots[0] $rel)
}
function Assert-Ok([string]$what) {
  if ($LASTEXITCODE -ne 0) { throw "$what a echoue (code $LASTEXITCODE)" }
}
function Invoke-SqlFile([string]$file) {
  psql -v ON_ERROR_STOP=1 -f $file $ExternalDatabaseUrl
  Assert-Ok "psql $file"
}

$circuits = Find-Dump "utf8\circuits_fixed.sql"
$guide = Find-Dump "utf8\guide_descriptions.sql"
$packSql = Find-Dump "00_pack_categorie.sql"
$histDump = Find-Dump "hist.dump"
$packsDump = Find-Dump "packs.dump"
$chunksSql = Find-Dump "utf8\chunks.sql"

foreach ($f in @($circuits, $packSql, $histDump)) {
  if (-not (Test-Path $f)) { throw "Fichier manquant: $f" }
}

$env:PGCLIENTENCODING = "UTF8"
Write-Host "Dossiers: $($roots -join ' ; ')"

Write-Host "0/5 extensions vector, pgcrypto, uuid-ossp"
if (-not $WhatIf) {
  foreach ($ext in @("vector", "pgcrypto", "uuid-ossp")) {
    "CREATE EXTENSION IF NOT EXISTS `"$ext`";" | psql -v ON_ERROR_STOP=1 -q -f - $ExternalDatabaseUrl
    if ($LASTEXITCODE -ne 0) {
      Write-Warning "Extension $ext indisponible sur ce serveur (la suite echouera si elle est requise)"
    }
  }
}

Write-Host "1/5 pack categorie enum -> $packSql"
if (-not $WhatIf) { Invoke-SqlFile $packSql }

Write-Host "2/5 circuits (UTF-8 fixed) -> $circuits"
if (-not $WhatIf) { Invoke-SqlFile $circuits }

if (Test-Path $chunksSql) {
  Write-Host "3/5 historical chunks SQL -> $chunksSql"
  if (-not $WhatIf) { Invoke-SqlFile $chunksSql }
} else {
  Write-Host "3/5 historical pg_restore -> $histDump"
  if (-not $WhatIf) {
    pg_restore --exit-on-error --no-owner --no-privileges -d $ExternalDatabaseUrl $histDump
    Assert-Ok "pg_restore hist.dump"
  }
}

if (-not $SkipPacks -and (Test-Path $packsDump)) {
  Write-Host "4/5 packs -> $packsDump"
  if (-not $WhatIf) {
    pg_restore --exit-on-error --no-owner --no-privileges -d $ExternalDatabaseUrl $packsDump
    Assert-Ok "pg_restore packs.dump"
  }
} else {
  Write-Host "4/5 packs skipped"
}

if (Test-Path $guide) {
  Write-Host "5/5 guide descriptions Excel (8 monuments) -> $guide"
  if (-not $WhatIf) { Invoke-SqlFile $guide }
} else {
  Write-Host "5/5 guide_descriptions.sql absent - lancer: python scripts/build_guide_descriptions.py"
}

if (-not $WhatIf) {
  @'
SELECT id, name_fr, length(description_fr) AS fr, length(description_en) AS en, length(description_ar) AS ar
FROM monuments WHERE id IN (1,2,12,23,24,25,43,44) ORDER BY id;
'@ | psql -v ON_ERROR_STOP=1 -f - $ExternalDatabaseUrl
  Assert-Ok "verification des descriptions"
}
Write-Host "Termine."
