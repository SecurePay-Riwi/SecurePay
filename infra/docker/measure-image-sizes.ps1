# Builds each image twice, with Dockerfile.baseline and with the repository's
# own Dockerfile, and writes sizes.csv here (ignored by git). Needs Docker and
# the five repositories cloned side by side. From the root of SecurePay:
#   powershell -ExecutionPolicy Bypass -File infra\docker\measure-image-sizes.ps1
$ErrorActionPreference = "Stop"
$env:DOCKER_BUILDKIT = "1"
$here = $PSScriptRoot
$root = Split-Path (Split-Path (Split-Path $here -Parent) -Parent) -Parent
$repos = @("SecurePay", "securepay-seed", "securepay-apis", "securepay-generator", "securepay-csv")
$rows = @()
foreach ($repo in $repos) {
    $ctx = Join-Path $root $repo
    $name = $repo.ToLower()
    Write-Host "== ${repo}: baseline"
    docker build -q -f (Join-Path $here "Dockerfile.baseline") -t "size-$($name):before" $ctx | Out-Null
    Write-Host "== ${repo}: current"
    docker build -q -f (Join-Path $ctx "Dockerfile") -t "size-$($name):after" $ctx | Out-Null
    $before = [int64](docker image inspect "size-$($name):before" --format "{{.Size}}")
    $after  = [int64](docker image inspect "size-$($name):after"  --format "{{.Size}}")
    $commit = (git -C $ctx rev-parse --short HEAD)
    $rows += [pscustomobject]@{
        image = $repo; commit = $commit
        before_mb = [math]::Round($before / 1MB); after_mb = [math]::Round($after / 1MB)
        saved_pct = [math]::Round(100 * (1 - $after / $before))
    }
}
$rows | Export-Csv -NoTypeInformation -Path (Join-Path $here "sizes.csv")
$rows | Format-Table -AutoSize
docker image ls "size-*"
