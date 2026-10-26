param(
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [switch]$ConfirmRestore
)

$ErrorActionPreference = "Stop"
if (-not $ConfirmRestore) {
    throw "Restore replaces current GerarAI data. Re-run with -ConfirmRestore."
}
$workspace = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$backup = [System.IO.Path]::GetFullPath($BackupPath)
if (-not $backup.StartsWith($workspace, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "BackupPath must be inside the GerarAI workspace."
}
if (-not (Test-Path -LiteralPath (Join-Path $backup "manifest.json"))) {
    throw "manifest.json was not found in the backup directory."
}
if (-not (Test-Path -LiteralPath (Join-Path $backup "postgres.dump"))) {
    throw "postgres.dump was not found in the backup directory."
}

docker compose stop backend worker scheduler frontend
docker compose up -d postgres
$postgres = (docker compose ps -q postgres).Trim()
if (-not $postgres) { throw "The postgres compose service did not start." }
docker cp (Join-Path $backup "postgres.dump") "${postgres}:/tmp/cavaai.dump"
docker exec $postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/cavaai.dump'
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed." }
docker exec $postgres rm -f /tmp/cavaai.dump

$volumeArchives = @(
    @{ Name = "cavaai-mongodb-data"; File = "mongodb.tar.gz"; Service = "mongodb" },
    @{ Name = "cavaai-qdrant-data"; File = "qdrant.tar.gz"; Service = "qdrant" },
    @{ Name = "cavaai-minio-data"; File = "minio.tar.gz"; Service = "minio" }
)
foreach ($item in $volumeArchives) {
    $archive = Join-Path $backup $item.File
    if (-not (Test-Path -LiteralPath $archive)) { continue }
    docker compose stop $item.Service
    docker volume create $item.Name | Out-Null
    docker run --rm `
        --mount "type=volume,source=$($item.Name),target=/target" `
        --mount "type=bind,source=$backup,target=/backup,readonly" `
        alpine:3.20 sh -c "rm -rf /target/* /target/.[!.]* /target/..?* 2>/dev/null || true; tar -C /target -xzf /backup/$($item.File)"
    if ($LASTEXITCODE -ne 0) { throw "Restore failed for $($item.Name)." }
}
docker compose up -d
Write-Output "Restore completed from: $backup"
