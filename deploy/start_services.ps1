# Smart Farm AI Platform - Service Startup Script
# Usage: cd C:\smart_farm && .\deploy\start_services.ps1

$PROJECT_ROOT = "C:\smart_farm"
$NGINX_DIR    = "C:\nginx"
$NGINX_EXE    = "$NGINX_DIR\nginx.exe"

Set-Location $PROJECT_ROOT

# -- 1. nginx --
Write-Host "[1/2] nginx ..." -ForegroundColor Cyan

$nginxRunning = Get-Process nginx -ErrorAction SilentlyContinue
if ($nginxRunning) {
    Write-Host "  nginx already running (PID: $($nginxRunning.Id))" -ForegroundColor Yellow
} elseif (Test-Path $NGINX_EXE) {
    Start-Process -FilePath $NGINX_EXE -WorkingDirectory $NGINX_DIR -WindowStyle Hidden
    Start-Sleep -Seconds 2
    $port80 = netstat -ano | Select-String ":80 " | Select-String "LISTENING"
    if ($port80) {
        Write-Host "  nginx OK - port 80 LISTENING" -ForegroundColor Green
    } else {
        Write-Host "  nginx FAILED - check: $NGINX_DIR\logs\error.log" -ForegroundColor Red
    }
} else {
    Write-Host "  nginx.exe not found: $NGINX_EXE" -ForegroundColor Red
}

# -- 2. FastAPI (uvicorn) --
Write-Host "[2/2] FastAPI (uvicorn) ..." -ForegroundColor Cyan

$port8000 = netstat -ano | Select-String ":8000 " | Select-String "LISTENING"
if ($port8000) {
    Write-Host "  uvicorn already running (port 8000)" -ForegroundColor Yellow
} else {
    Start-Process -FilePath "python" `
        -ArgumentList "-m uvicorn api.main:app --host 0.0.0.0 --port 8000" `
        -WorkingDirectory $PROJECT_ROOT `
        -WindowStyle Minimized

    $waited = 0
    do {
        Start-Sleep -Seconds 1
        $waited++
        $up = netstat -ano | Select-String ":8000 " | Select-String "LISTENING"
    } while (-not $up -and $waited -lt 10)

    if ($up) {
        Write-Host "  uvicorn OK - port 8000 LISTENING ($waited s)" -ForegroundColor Green
    } else {
        Write-Host "  uvicorn FAILED. Run manually:" -ForegroundColor Red
        Write-Host "  python -m uvicorn api.main:app --host 0.0.0.0 --port 8000" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "--- Access URLs ---" -ForegroundColor DarkGray
Write-Host "  Dashboard (nginx): http://localhost/"        -ForegroundColor Green
Write-Host "  API direct:        http://localhost:8000/"   -ForegroundColor Green
Write-Host "  Swagger:           http://localhost/docs"    -ForegroundColor Green
Write-Host "-------------------" -ForegroundColor DarkGray
