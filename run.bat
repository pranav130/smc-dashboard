@echo off
title XAUTUSD SMC & Paper Trading Dashboard
cd /d "%~dp0"
echo ==========================================================
echo   Starting XAUTUSD SMC ^& Paper Trading Dashboard (v1.1)
echo   Local URL: http://127.0.0.1:8000
echo   Paper URL: http://127.0.0.1:8000/paper
echo ==========================================================
uv run uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
pause
