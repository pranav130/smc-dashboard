# XAUTUSD Dashboard & 24/7 Paper Trading — Cloud Deployment Guide

This guide provides step-by-step instructions to deploy the XAUTUSD SMC Dashboard and 24/7 Paper Trading Command Center to the cloud with persistent records and custom domain routing via Zoho Domains.

---

## 1. Architecture Overview

- **Frontend**: Pure HTML5, CSS3, JavaScript, and TradingView Lightweight Charts (no compilation/build step required).
- **Backend**: Python 3.12, FastAPI, Uvicorn asynchronous ASGI server.
- **Market Data Feed**: Delta Exchange India public WebSocket + REST API fallback (`.DEXAUTUSD` Gold Index / `XAUTUSD` Futures). Zero exchange credentials required.
- **24/7 Market Monitoring**: Asynchronous background monitor loop running in the application process, continuously tracking market levels, evaluating SMC setups, and checking open position stop-loss/take-profit triggers even when no browser is open.
- **Database & Persistence**: SQLAlchemy 2.0 with PostgreSQL for cloud deployments (and local SQLite fallback). Open positions, closed trades, logs, and account balances are retained across redeployments and server restarts.
- **Execution Mode**: Hardcoded to `PAPER` simulation. No real money or exchange order routing.

---

## 2. Recommended Cloud Architecture (Render)

### Why Render?
- Native support for Python 3.12 WebSockets.
- Managed PostgreSQL with automated daily backups and zero-downtime maintenance.
- Starter Web Service plan stays active 24/7 without sleeping or spinning down.
- Built-in Let's Encrypt automated SSL/TLS certificate management.
- Simple CNAME DNS custom domain verification.

### Monthly Hosting Cost Breakdown

| Component | Provider & Tier | Verified Pricing | Function |
| :--- | :--- | :--- | :--- |
| **Web Service** | Render Starter | **$7.00 / month** | Runs FastAPI, WebSockets & 24/7 background monitor |
| **PostgreSQL Database** | Render Managed Starter | **$7.00 / month** | 256MB RAM, 1GB persistent disk, automated backups |
| **Domain & DNS** | Zoho Domains | Pre-owned by user | Domain registrar & DNS routing |
| **Total Estimated Cost** | — | **~$14.00 / month** | — |

*Alternative (Railway)*: Railway Hobby plan provides $5/month base usage credit covering lightweight Python + Postgres containers.

---

## 3. Step-by-Step Deployment Instructions (Render)

### Step 1: Push Code to GitHub
1. Open your terminal in the project directory:
   ```bash
   cd C:\Users\tripa\smc-dashboard
   ```
2. Verify you are on `master`:
   ```bash
   git checkout master
   git status
   ```
3. Commit and push your changes to a private or public GitHub repository:
   ```bash
   git add .
   git commit -m "feat: 24/7 cloud paper trading engine, health checks, and deployment configuration"
   git remote add origin https://github.com/YOUR_USERNAME/smc-dashboard.git
   git push -u origin master
   ```

### Step 2: Create Managed PostgreSQL on Render
1. Log in to [Render Dashboard](https://dashboard.render.com).
2. Click **New +** &rarr; **PostgreSQL**.
3. Name: `smc-postgres`
4. Database: `smc_paper_trading`
5. User: `smc_user`
6. Region: Choose the region closest to India/Singapore (e.g., `Singapore` or `Frankfurt`).
7. Plan: **Starter** ($7/mo).
8. Click **Create Database**.
9. Once provisioned, copy the **Internal Database URL** (e.g., `postgres://smc_user:...@dpg-.../smc_paper_trading`).

### Step 3: Deploy the Web Service
1. Click **New +** &rarr; **Web Service**.
2. Connect your GitHub repository `smc-dashboard`.
3. Configure the service settings:
   - **Name**: `smc-dashboard`
   - **Region**: Same region as your database.
   - **Branch**: `master`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn backend.app:app --host 0.0.0.0 --port $PORT`
   - **Plan**: **Starter** ($7/mo).
4. Under **Advanced** &rarr; **Environment Variables**, add:
   - `PYTHON_VERSION` = `3.12.0`
   - `ENVIRONMENT` = `production`
   - `EXECUTION_MODE` = `PAPER`
   - `DELTA_PRICE_SOURCE` = `index`
   - `DATABASE_URL` = *(Paste Internal Database URL from Step 2)*
   - `ALLOWED_ORIGINS` = `*`
   - `INITIAL_PAPER_BALANCE` = `10000.0`
   - `AUTO_PAPER_TRADING_ENABLED` = `true`
   - `ADMIN_API_KEY` = *(Choose a secure password/token for admin actions)*
5. Under **Health Check Path**, enter: `/health`
6. Click **Create Web Service**.

Render will build the project and output logs:
```
==> Initializing persistent database schema...
==> Initialized persistent paper trading account with $10,000.00 USD
==> Starting SMC Dashboard backend for .DEXAUTUSD...
==> 24/7 Background Market Monitoring loop started.
==> Application startup complete.
```

---

## 4. Connecting Your Custom Subdomain in Zoho Domains

> [!IMPORTANT]
> **Preserve Existing Records**: When adding records in Zoho Domains, **do not touch or delete** your existing MX, SPF, DKIM, or DMARC records. Those records handle your email delivery.

### Step 1: Add Custom Domain in Render
1. Go to your `smc-dashboard` service in the Render Dashboard.
2. Navigate to **Settings** &rarr; **Custom Domains**.
3. Click **Add Custom Domain**.
4. Enter your desired subdomain:
   ```
   dashboard.MYDOMAIN.com
   ```
   *(Replace MYDOMAIN.com with your domain registered in Zoho)*
5. Render will show the target verification host, typically:
   ```
   smc-dashboard.onrender.com
   ```

### Step 2: Add CNAME Record in Zoho Domains
1. Sign in to your Zoho Domains account at:
   https://accounts.zoho.in/signin?servicename=ZohoDomains
2. Open your domain and select **DNS Management** (or **DNS Records**).
3. Click **Add Record**:
   - **Type**: `CNAME`
   - **Name / Host**: `dashboard`
   - **Value / Points to**: `smc-dashboard.onrender.com`
   - **TTL**: `300` seconds (or `Auto` / `1 Hour`)
4. Save the record.

### Step 3: SSL Verification
- Within 5–15 minutes, Render will detect the CNAME record and automatically issue a free Let's Encrypt TLS/SSL certificate.
- Your dashboard will be live at: `https://dashboard.MYDOMAIN.com`

---

## 5. Verification & Rollback Procedures

### Verification Checklist
1. Visit `https://dashboard.MYDOMAIN.com/health` &rarr; verify `{"status": "healthy", "database": "connected"}`.
2. Visit `https://dashboard.MYDOMAIN.com/` &rarr; verify candlestick chart and SMC levels load.
3. Click the **Paper Trading ↗** button in the header &rarr; verify Paper Trading Command Center opens in a new tab.
4. Check that balance displays `$10,000.00 USD`.
5. Trigger a simulated order or wait for an SMC setup &rarr; verify it appears in Active Open Positions.
6. Trigger a redeploy in Render &rarr; refresh the page and verify positions and account balance remain preserved.

### Rollback Guidance
- In Render: Go to **Events** &rarr; select the previous successful deploy &rarr; click **Rollback**.
- To reset paper account: Click **Reset Balance** on the Paper Trading dashboard.
