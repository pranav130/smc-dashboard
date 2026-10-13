# Startup script for SMC Key-Level Intelligence Dashboard
$env:Path = "C:\Users\tripa\.local\bin;$env:Path"
$env:PYTHONPATH = "."
Write-Host "==========================================================" -ForegroundColor Yellow
Write-Host "  Starting SMC Key-Level Intelligence Dashboard (Delta India)  " -ForegroundColor Cyan
Write-Host "  Instrument: XAUTUSD (Tether Gold Perpetual Future)      " -ForegroundColor Green
Write-Host "  API: https://api.india.delta.exchange                  " -ForegroundColor Green
Write-Host "  URL: http://127.0.0.1:8000                             " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Yellow

uv run --python 3.12 --with fastapi --with uvicorn --with httpx --with websockets --with pydantic --with python-dateutil python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
