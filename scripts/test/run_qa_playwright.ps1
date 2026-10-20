param(
    [Parameter(Mandatory = $true)]
    [string[]]$Specs
)

$ErrorActionPreference = 'Stop'
$requiredVariables = @(
    'QC_E2E_BASE_URL',
    'CSV_QA_BASE_URL',
    'CSV_QA_COMPOSE_PROJECT',
    'CSV_QA_DOCKER_CONTEXT',
    'CSV_QA_ENV_FILE',
    'CSV_QA_COMPOSE_OVERRIDE_FILE',
    'CSV_QA_FIXTURE',
    'QC_E2E_OUTPUT_DIR'
)

foreach ($name in $requiredVariables) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "QA browser preflight failed: $name is required. Playwright was not started and no HTTP request was made."
    }
}

$repositoryRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$artifactsRoot = [IO.Path]::GetFullPath((Join-Path $repositoryRoot 'artifacts')).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar

function Resolve-ArtifactPath([string]$name, [string]$value) {
    $candidate = $value
    if (-not [IO.Path]::IsPathRooted($candidate)) {
        $candidate = Join-Path $repositoryRoot $candidate
    }
    $fullPath = [IO.Path]::GetFullPath($candidate)
    if (-not $fullPath.StartsWith($artifactsRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "QA browser preflight failed: $name must be inside this run's artifacts directory. Playwright was not started."
    }
    return $fullPath
}

$outputDirectory = Resolve-ArtifactPath 'QC_E2E_OUTPUT_DIR' $env:QC_E2E_OUTPUT_DIR
if (Test-Path -LiteralPath $outputDirectory -PathType Leaf) {
    throw 'QA browser preflight failed: QC_E2E_OUTPUT_DIR must be a new or empty directory. Playwright was not started.'
}
if ((Test-Path -LiteralPath $outputDirectory -PathType Container) -and
    @(Get-ChildItem -LiteralPath $outputDirectory -Force).Count -gt 0) {
    throw 'QA browser preflight failed: choose a new empty QC_E2E_OUTPUT_DIR so earlier evidence is preserved. Playwright was not started.'
}

$isCsvSpec = @($Specs | ForEach-Object { $_ -replace '\\', '/' } | Where-Object { $_ -like '*csv-header-validation.spec.ts' }).Count -gt 0
if ($isCsvSpec) {
    foreach ($name in @('CSV_INVALID_FIXTURE', 'CSV_CORRECTED_FIXTURE', 'CSV_HEADER_ACCEPTANCE_REPORT')) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
            throw "QA browser preflight failed: $name is required for CSV acceptance. Playwright was not started."
        }
    }
    foreach ($name in @('CSV_INVALID_FIXTURE', 'CSV_CORRECTED_FIXTURE')) {
        $fixturePath = Resolve-ArtifactPath $name ([Environment]::GetEnvironmentVariable($name))
        if (-not (Test-Path -LiteralPath $fixturePath -PathType Leaf)) {
            throw "QA browser preflight failed: $name must point to an existing test fixture. Playwright was not started."
        }
    }
    $reportPath = Resolve-ArtifactPath 'CSV_HEADER_ACCEPTANCE_REPORT' $env:CSV_HEADER_ACCEPTANCE_REPORT
    if (Test-Path -LiteralPath $reportPath) {
        throw 'QA browser preflight failed: CSV_HEADER_ACCEPTANCE_REPORT must be a new file so earlier evidence is preserved. Playwright was not started.'
    }
}

if ($env:QC_E2E_BASE_URL -ne $env:CSV_QA_BASE_URL) {
    throw 'QA browser preflight failed: QC_E2E_BASE_URL and CSV_QA_BASE_URL must match. No browser was started.'
}

$qaUrl = $null
if (-not [Uri]::TryCreate($env:QC_E2E_BASE_URL, [UriKind]::Absolute, [ref]$qaUrl) -or
    $qaUrl.Scheme -ne 'http' -or $qaUrl.Host -ne '127.0.0.1' -or
    $env:QC_E2E_BASE_URL -notmatch '^http://127\.0\.0\.1:\d+/?$' -or $qaUrl.Port -eq 80) {
    throw 'QA browser preflight failed: use an explicit http://127.0.0.1:<isolated-port> URL, never port 80. No browser was started.'
}

$env:QC_E2E_REQUIRE_COMPOSE_PREFLIGHT = '1'
$frontendRoot = Join-Path $repositoryRoot 'frontend'
$playwrightCli = Join-Path $frontendRoot 'node_modules\.bin\playwright.cmd'
if (-not (Test-Path -LiteralPath $playwrightCli -PathType Leaf)) {
    throw 'QA browser preflight failed: install the checked-out frontend dependencies before launching Playwright.'
}

$previousRunToken = $env:QC_E2E_RUN_TOKEN
$previousRunMarker = $env:QC_E2E_RUN_MARKER_FILE
$runToken = [guid]::NewGuid().ToString('N')
if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
    New-Item -ItemType Directory -Path $outputDirectory | Out-Null
}
$runMarker = Join-Path (Split-Path -Parent $outputDirectory) ".qa-run-$runToken.marker"
[IO.File]::WriteAllText($runMarker, $runToken, [System.Text.UTF8Encoding]::new($false))
$env:QC_E2E_RUN_TOKEN = $runToken
$env:QC_E2E_RUN_MARKER_FILE = $runMarker

Push-Location $frontendRoot
try {
    & $playwrightCli test --config playwright.config.ts @Specs
    $playwrightExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    if ((Test-Path -LiteralPath $runMarker -PathType Leaf) -and
        [IO.File]::ReadAllText($runMarker) -eq $runToken) {
        Remove-Item -LiteralPath $runMarker -Force
    }
    if ([string]::IsNullOrWhiteSpace($previousRunMarker)) {
        Remove-Item Env:QC_E2E_RUN_MARKER_FILE -ErrorAction SilentlyContinue
    } else {
        $env:QC_E2E_RUN_MARKER_FILE = $previousRunMarker
    }
    if ([string]::IsNullOrWhiteSpace($previousRunToken)) {
        Remove-Item Env:QC_E2E_RUN_TOKEN -ErrorAction SilentlyContinue
    } else {
        $env:QC_E2E_RUN_TOKEN = $previousRunToken
    }
}

exit $playwrightExitCode
