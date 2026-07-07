# DataDog Complete Setup Script (.NET Tracer + Configuration)
# Run this script as administrator
# APM is enabled for all environments: Dev, QA, Stage, and Production

param(
    [Parameter(Mandatory=$false)]
    [string]$TracerVersion = "2.14.0", # Version of .NET Tracer to install

    [Parameter(Mandatory=$false)]
    [string]$AgentVersion = "7.39.1",

    [Parameter(Mandatory=$false)]
    [string]$EnvironmentName = "development",

    [Parameter(Mandatory=$false)]
    [string]$Region = "local",

    [Parameter(Mandatory=$false)]
    [string]$ServiceName = "sample-dotnet-api",

    [Parameter(Mandatory=$false)]
    [string]$LogsPath = "C:\Logs\sample-dotnet-api-*.*"
)

# ── Environments where APM tracing must be enabled ──
$APMEnabledEnvironments = @("dev", "qa", "stage", "production")

# Function to check if running as administrator
function Test-Admin {
    $currentUser = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    return $currentUser.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

# Check if running as administrator
if (-not (Test-Admin)) {
    Write-Host "This script needs to be run as Administrator. Please restart PowerShell as an Administrator." -ForegroundColor Red
    exit
}

#############################################
# PART 1: Check and Install DataDog Agent
#############################################
Write-Host "Environment test = $EnvironmentName"

Write-Host "=== CHECKING DATADOG AGENT INSTALLATION ===" -ForegroundColor Magenta

# Function to check if DataDog Agent is installed and get its version
function Get-DatadogAgentVersion {
    $agentService = Get-Service -Name "datadogagent" -ErrorAction SilentlyContinue

    if ($agentService) {
        $agentExe = "C:\Program Files\Datadog\Datadog Agent\bin\agent.exe"

        if (Test-Path $agentExe) {
            try {
                $versionOutput = & $agentExe version
                if ($versionOutput -match "Agent\s+(\d+\.\d+\.\d+(\.\d+)?)") {
                    return $matches[1]
                }
            } catch {
                Write-Host "Error checking agent version: $_" -ForegroundColor Yellow
            }
        }
        return "Unknown"
    }
    return $null
}

# Check if DataDog Agent is already installed
$installedVersion = Get-DatadogAgentVersion

if ($installedVersion -eq $AgentVersion) {
    Write-Host "DataDog Agent v$AgentVersion is already installed." -ForegroundColor Green
    Write-Output "#### DataDog Agent $AgentVersion already installed ####"
} else {
    Write-Output "#### Installing Datadog Agent $AgentVersion ####"
    if ($installedVersion) {
        Write-Host "DataDog Agent v$installedVersion is currently installed. Will update to v$AgentVersion." -ForegroundColor Yellow
    } else {
        Write-Host "=== INSTALLING DATADOG AGENT v$AgentVersion ===" -ForegroundColor Magenta
    }

    # Construct the URL for the specific version
    $agentUrl = "https://s3.amazonaws.com/ddagent-windows-stable/ddagent-cli-$AgentVersion.msi"

    try {
        # Download the specific agent version
        $agentInstallerPath = "$env:TEMP\datadog-agent-$AgentVersion-amd64.msi"
        Write-Host "Downloading DataDog Agent v$AgentVersion..." -ForegroundColor Cyan

        Invoke-WebRequest -Uri $agentUrl -OutFile $agentInstallerPath -UseBasicParsing

        if (-not (Test-Path $agentInstallerPath)) {
            throw "Failed to download agent installer"
        }

        # Install the DataDog Agent
        Write-Host "Installing DataDog Agent v$AgentVersion..." -ForegroundColor Cyan
        $DatadogApiKey = $env:DD_API_KEY
$DatadogSite = if ($env:DD_SITE) { $env:DD_SITE } else { "datadoghq.com" }

if (-not $DatadogApiKey) {
    throw "DD_API_KEY environment variable is required. Do not hardcode API keys in this script."
}

Start-Process "msiexec.exe" -ArgumentList @(
    "/i",
    $agentInstallerPath,
    "APIKEY=""$DatadogApiKey"" SITE=""$DatadogSite""",
    "/quiet"
) -Verb RunAs -Wait

        # Clean up the installer
        if (Test-Path $agentInstallerPath) {
            Remove-Item $agentInstallerPath -Force
        }

        Write-Host "DataDog Agent v$AgentVersion installed successfully" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to install DataDog Agent: $_" -ForegroundColor Red
        Write-Host "Continuing with other steps..." -ForegroundColor Yellow
    }
    Write-Output "#### Installed Datadog Agent v$AgentVersion ####"
}

#############################################
# PART 2: Install DataDog .NET Tracer
#############################################

Write-Host "=== INSTALLING DATADOG .NET TRACER v$TracerVersion ===" -ForegroundColor Magenta
Write-Output "#### Installing Datadog .Net Tracer ####"

$downloadUrl = "https://github.com/DataDog/dd-trace-dotnet/releases/download/v$TracerVersion/datadog-dotnet-apm-$TracerVersion-x64.msi"
$installerPath = "$env:TEMP\datadog-dotnet-apm-$TracerVersion-x64.msi"

# Set TLS 1.2
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# Download the .NET Tracer
Write-Host "Downloading DataDog .NET Tracer v$TracerVersion..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing

    if (Test-Path $installerPath) {
        $fileSize = (Get-Item $installerPath).Length
        Write-Host "Download successful: $installerPath ($fileSize bytes)" -ForegroundColor Green
    } else {
        throw "Downloaded file not found at $installerPath"
    }
} catch {
    Write-Host "ERROR: Failed to download DataDog .NET Tracer: $_" -ForegroundColor Red

    # Try alternative URL as fallback
    try {
        Write-Host "Trying alternative download URL..." -ForegroundColor Yellow
        $alternativeUrl = "https://dtdg.co/net-tracer-msi"
        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($alternativeUrl, $installerPath)

        if (Test-Path $installerPath) {
            Write-Host "Download from alternative URL successful" -ForegroundColor Green
        } else {
            throw "Alternative download also failed"
        }
    } catch {
        Write-Host "ERROR: All download attempts failed. Please check your internet connection and try again." -ForegroundColor Red
        exit
    }
}

# Install the .NET Tracer
Write-Host "Installing DataDog .NET Tracer v$TracerVersion..." -ForegroundColor Cyan
try {
    $process = Start-Process -FilePath "msiexec.exe" -ArgumentList "/i `"$installerPath`" /qn" -Wait -NoNewWindow -PassThru

    if ($process.ExitCode -eq 0) {
        Write-Host "Installation successful with exit code: $($process.ExitCode)" -ForegroundColor Green
    } else {
        throw "Installation failed with exit code: $($process.ExitCode)"
    }
} catch {
    Write-Host "ERROR: Failed to install DataDog .NET Tracer: $_" -ForegroundColor Red
    exit
}

# Cleanup
if (Test-Path $installerPath) {
    Remove-Item $installerPath -Force
    Write-Host "Installer file cleaned up" -ForegroundColor Gray
}

# Verify installation
Write-Host "Verifying .NET Tracer installation..." -ForegroundColor Cyan
$tracerPath = "C:\Program Files\Datadog\.NET Tracer"

if (Test-Path $tracerPath) {
    $tracerDlls = Get-ChildItem -Path $tracerPath -Filter "Datadog.Trace*.dll" -Recurse

    if ($tracerDlls.Count -gt 0) {
        Write-Host "Installed .NET Tracer files at: $tracerPath" -ForegroundColor Green
        Write-Output "#### Installed DataDog .Net Tracer ####"
        $sampleDll = $tracerDlls | Select-Object -First 1
        $versionInfo = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($sampleDll.FullName)
        Write-Host "Installed version: $($versionInfo.FileVersion)" -ForegroundColor Green
    } else {
        Write-Host "WARNING: .NET Tracer directory exists but no DLLs found" -ForegroundColor Yellow
    }
} else {
    Write-Host "WARNING: .NET Tracer directory not found at $tracerPath" -ForegroundColor Yellow
}

#############################################
# PART 3: Configure DataDog Agent
#############################################

Write-Host "`n=== CONFIGURING DATADOG AGENT FOR SAMPLE .NET SERVICE ($Region) ===" -ForegroundColor Magenta

# Step 1: Enable tracing in datadog.yaml
$datadogYamlPath = "C:\ProgramData\Datadog\datadog.yaml"

if (-not (Test-Path $datadogYamlPath)) {
    Write-Host "ERROR: DataDog configuration file not found at $datadogYamlPath" -ForegroundColor Red
    Write-Host "Continuing with other steps..." -ForegroundColor Yellow
} else {
    Write-Host "Updating DataDog configuration file to enable tracing..." -ForegroundColor Cyan

    # Read the file content
    $content = Get-Content $datadogYamlPath -Raw

    Write-Output "#### Configure Datadog Agent ####"

    # Apply all required configuration changes
    # Enable logs
    $content = (Get-Content $datadogYamlPath -Raw) -Replace "# logs_enabled: false", "logs_enabled: true"

    # Enable process config
    $content = $content -Replace "# process_config:", "process_config:`n  enabled: true"

    # Set dogstatsd port
    $content = $content -Replace "# dogstatsd_port: 8125", "dogstatsd_port: 8121"

    # Set environment
    $content = $content -Replace "# env: <environment name>", "env: $EnvironmentName"

    # ──────────────────────────────────────────────────
    # APM Configuration – enabled for Dev, QA, Stage, and Production
    # ──────────────────────────────────────────────────
    # Normalise the current environment name for comparison
    $envNormalised = ($EnvironmentName -replace '\s', '').ToLower()

    if ($APMEnabledEnvironments -contains $envNormalised) {
        Write-Host "Environment '$EnvironmentName' is in the APM-enabled list ($($APMEnabledEnvironments -join ', ')). Enabling APM..." -ForegroundColor Cyan

        if ($content -match "apm_config:\s*\r?\n\s*enabled:\s*true") {
            Write-Host "APM tracing is already enabled in the configuration file." -ForegroundColor Green
        } else {
            # Replace the commented apm_config section with an enabled one
            $pattern = "# apm_config:[\s\S]*?# enabled: true"
            $replacement = "apm_config:`n  enabled: true"

            $content = $content -replace $pattern, $replacement

            # If the pattern wasn't found or replaced, try inserting it
            if (-not ($content -match "apm_config:\s*\r?\n\s*enabled:\s*true")) {
                Write-Host "Could not find the commented apm_config section. Appending APM config..." -ForegroundColor Yellow

                # Add the configuration at the end of the file
                $content = $content + "`n`n# APM tracing configuration (enabled for $EnvironmentName)`napm_config:`n  enabled: true`n"
            }
        }

        Write-Host "APM tracing ENABLED for environment: $EnvironmentName" -ForegroundColor Green
    } else {
        Write-Host "WARNING: Environment '$EnvironmentName' is NOT in the APM-enabled list ($($APMEnabledEnvironments -join ', ')). APM will NOT be enabled." -ForegroundColor Yellow
    }

    # Write all changes back to the file
    Set-Content -Path $datadogYamlPath -Value $content
    Write-Host "DataDog configuration file updated successfully." -ForegroundColor Green
    Write-Output "#### Configure Datadog Agent Complete ####"

    # Step 2: Configure logging
    Write-Host "Configuring DataDog logging..." -ForegroundColor Cyan

    # Create the logging configuration folder
    $logFolderName = "$ServiceName-$Region.d"
    $logFolderPath = "C:\ProgramData\Datadog\conf.d\$logFolderName"

    if (-not (Test-Path $logFolderPath)) {
        New-Item -Path $logFolderPath -ItemType Directory -Force | Out-Null
        Write-Host "Created logging configuration folder: $logFolderPath" -ForegroundColor Green
    } else {
        Write-Host "Logging configuration folder already exists: $logFolderPath" -ForegroundColor Green
    }

    # Create the logging configuration file
    $logConfigPath = "$logFolderPath\conf.yaml"
    $logConfigContent = @"
    logs:
      - type: file
        path: '$LogsPath'
        service: $ServiceName
        source: dotnet
        sourcecategory: sourcecode
    "@

    Set-Content -Path $logConfigPath -Value $logConfigContent
    Write-Host "Created logging configuration file: $logConfigPath" -ForegroundColor Green
}

#############################################
# PART 4: Restart Services
#############################################

Write-Host "`n=== RESTARTING SERVICES ===" -ForegroundColor Magenta

# Restart DataDog Agent service
Write-Host "Restarting DataDog Agent service..." -ForegroundColor Cyan
try {
    $service = Get-Service -Name "datadogagent" -ErrorAction SilentlyContinue
    if ($service) {
        Restart-Service -Name "datadogagent" -Force -ErrorAction Stop
        Write-Host "DataDog Agent service restarted successfully." -ForegroundColor Green
    } else {
        Write-Host "WARNING: DataDog Agent service not found." -ForegroundColor Yellow
    }
} catch {
    Write-Host "WARNING: Failed to restart DataDog Agent service: $_" -ForegroundColor Yellow
}

#############################################
# PART 5: Verify Configuration
#############################################

Write-Host "`n=== VERIFYING CONFIGURATION ===" -ForegroundColor Magenta

# Wait a moment for services to fully start
Write-Host "Waiting for services to initialize..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

Write-Output "#### Running Datadog Agent Status Check ####"
& "C:\Program Files\Datadog\Datadog Agent\bin\agent.exe" status
Write-Output "#### Datadog Agent Status Check Complete ####"

Write-Host "`n=== DATADOG SETUP COMPLETE! ===" -ForegroundColor Magenta
Write-Host "DataDog Agent v$AgentVersion has been installed" -ForegroundColor Green
Write-Host "DataDog .NET Tracer v$TracerVersion has been installed" -ForegroundColor Green
Write-Host "Datadog Agent has been configured for $ServiceName in $Region region" -ForegroundColor Green

# Print APM status summary
if ($APMEnabledEnvironments -contains $envNormalised) {
    Write-Host "APM tracing is ENABLED for environment: $EnvironmentName" -ForegroundColor Green
} else {
    Write-Host "APM tracing is NOT enabled for environment: $EnvironmentName" -ForegroundColor Yellow
}
