$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location -LiteralPath $PSScriptRoot

$appUrl = "http://localhost:8001"
$dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
$dockerBin = Join-Path $env:ProgramFiles "Docker\Docker\resources\bin"
if (Test-Path (Join-Path $dockerBin "docker.exe")) {
    $env:Path = "$dockerBin;$env:Path"
}

function Wait-KeyIfFailed {
    param([string]$Message)
    Write-Host ""
    Write-Host $Message -ForegroundColor Red
    Write-Host "Нажмите Enter, чтобы закрыть окно."
    [void](Read-Host)
    exit 1
}

Write-Host ""
Write-Host "=== CH-CRM ===" -ForegroundColor Cyan
Write-Host "Папка: $PWD"
Write-Host ""

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Wait-KeyIfFailed "Не найден docker. Установите Docker Desktop и перезагрузите компьютер.`nhttps://www.docker.com/products/docker-desktop/"
}

function Test-DockerReady {
    docker info 1>$null 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Test-PortOpen {
    param([int]$Port)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(800) -and $client.Connected
        $client.Close()
        return [bool]$ok
    } catch {
        return $false
    }
}

function Start-Umnik {
    $umnikRoot = if ($env:UMNIK_HOME) { $env:UMNIK_HOME } else { Join-Path $PSScriptRoot "umnik" }
    $py = Join-Path $umnikRoot ".venv\Scripts\python.exe"
    $server = Join-Path $umnikRoot "mcp_server.py"

    if (Test-PortOpen 7861) {
        Write-Host "Умник уже слушает :7861." -ForegroundColor Green
        return
    }
    if (-not (Test-Path -LiteralPath $py) -or -not (Test-Path -LiteralPath $server)) {
        Write-Host "Умник не найден в $umnikRoot — чат в CRM пока не ответит." -ForegroundColor Yellow
        Write-Host "Нужны $py и mcp_server.py. Потом снова start.bat."
        return
    }

    Write-Host "Запускаю умник (MCP :7861). Это окно не закрывайте."
    $env:PYTHONUTF8 = "1"
    $env:MCP_NO_OPENROUTER = "1"
    Start-Process -FilePath "cmd.exe" -WorkingDirectory $umnikRoot -ArgumentList @(
        "/k",
        "title Умник MCP 7861 && `"$py`" `"$server`" --http --host 0.0.0.0 --port 7861"
    ) | Out-Null

    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        if (Test-PortOpen 7861) {
            $ready = $true
            break
        }
        Write-Host "." -NoNewline
    }
    Write-Host ""
    if ($ready) {
        Write-Host "Умник готов." -ForegroundColor Green
    } else {
        Write-Host "Умник не поднялся за 30 секунд. Смотрите окно «Умник MCP 7861»." -ForegroundColor Yellow
        Write-Host "CRM при этом уже работает. Чат умника заработает, когда :7861 заговорит."
    }
}

if (-not (Test-DockerReady)) {
    Write-Host "Docker Desktop не запущен — запускаю..."
    if (-not (Test-Path -LiteralPath $dockerDesktop)) {
        Wait-KeyIfFailed "Не найден Docker Desktop. Установите его и запустите вручную."
    }
    Start-Process -FilePath $dockerDesktop | Out-Null
    Write-Host "Жду готовности Docker (до 2 минут)..."
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        if (Test-DockerReady) {
            $ready = $true
            break
        }
        Write-Host "." -NoNewline
    }
    Write-Host ""
    if (-not $ready) {
        Wait-KeyIfFailed "Docker так и не поднялся. Откройте Docker Desktop, дождитесь зелёного статуса и запустите start.bat снова."
    }
}

Write-Host "Docker готов." -ForegroundColor Green

if (-not (Test-Path -LiteralPath ".env")) {
    if (Test-Path -LiteralPath ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Создал .env из .env.example. При переносе на другой комп проверьте пути и ключи в .env."
    } else {
        Wait-KeyIfFailed "Нет файла .env и нет .env.example. Без них система не стартует."
    }
}

Write-Host "Запускаю контейнеры..."
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Wait-KeyIfFailed "Не удалось запустить docker compose.`nЕсли ошибка про D:\Общая_Рабочая или D:\Scan_Pdf — создайте эти папки или поправьте пути в docker-compose.yml."
}

Start-Umnik

Write-Host "Жду сайт на $appUrl ..."
$siteUp = $false
for ($i = 0; $i -lt 45; $i++) {
    try {
        $response = Invoke-WebRequest -Uri $appUrl -UseBasicParsing -TimeoutSec 3 -MaximumRedirection 5
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
            $siteUp = $true
            break
        }
    } catch {
        # сайт ещё не поднялся
    }
    Start-Sleep -Seconds 2
}

Start-Process $appUrl | Out-Null
if ($siteUp) {
    Write-Host "Сайт отвечает. Открыл браузер." -ForegroundColor Green
} else {
    Write-Host "Контейнеры запущены, но сайт пока не отвечает." -ForegroundColor Yellow
    Write-Host "Смотрите логи: docker compose logs app --tail=80"
}

Write-Host ""
Write-Host "Готово. CRM: $appUrl"
Write-Host "Это окно можно закрыть."
Start-Sleep -Seconds 8
exit 0
