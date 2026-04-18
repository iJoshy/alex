# Alex x Raenest Integration Blueprint

## Goal

Adapt Alex into a **Raenest-ready intelligence engine** for users buying US shares:

- Sync trade activity from Raenest into Alex portfolios
- Generate portfolio intelligence tailored to cross-border US equity investors
- Trigger AI analysis from Raenest backend workflows
- Keep existing Alex flows intact

---

## What Was Added (Improvements, Changes, Tweaks)

### 1. New Raenest Server-to-Server API Layer

Added protected endpoints in `backend/api/main.py` under `/api/raenest/*`:

1. `POST /api/raenest/sync-trades`
2. `GET /api/raenest/portfolio-intelligence/{clerk_user_id}`
3. `POST /api/raenest/trigger-analysis`

These endpoints are guarded with `x-raenest-api-key` and can be called directly from Raenest backend services.

### 2. Trade Sync Engine for US Share Activity

`sync-trades` now:

- Creates user/account records if needed (integration-friendly bootstrapping)
- Applies buy/sell trades in order
- Updates positions with upsert logic
- Handles full close-out (quantity becomes zero -> delete position)
- Updates account cash balance in USD using execution price + fees
- Returns sync summary with optional NGN conversion

### 3. Portfolio Intelligence Snapshot Built for Raenest UX

`portfolio-intelligence` returns:

- Total cash, market value, and total portfolio value (USD)
- Optional NGN conversions using provided FX rate
- Top holdings
- Sector exposure
- Concentration flags (e.g., holdings over 25%)

This is designed to drop directly into Raenest app dashboards and notifications.

### 4. Remote Analysis Trigger for Product Workflows

`trigger-analysis` allows Raenest backend to enqueue AI analysis after:

- Trade sync completion
- New user funding
- Scheduled review cycles

This makes orchestration easy without requiring end-user JWT flow from Raenest backend services.

### 5. Configuration & Operational Hardening

Updated `.env.example` with:

- `RAENEST_API_KEY`
- `RESEARCHER_MCP_TIMEOUT_SECONDS`
- `RESEARCHER_MAX_TURNS`
- `RESEARCHER_REQUEST_TIMEOUT_SECONDS`

So teams can run securely and tune reliability quickly.

---

## Endpoint Contracts

## 1) Sync trades from Raenest

`POST /api/raenest/sync-trades`

Headers:

```http
x-raenest-api-key: <RAENEST_API_KEY>
Content-Type: application/json
```

Request:

```json
{
  "clerk_user_id": "user_2w7abc...",
  "account_name": "Raenest US Stocks",
  "base_currency": "NGN",
  "fx_rate_ngn_per_usd": 1540.25,
  "trades": [
    {
      "symbol": "AAPL",
      "side": "buy",
      "quantity": 3.25,
      "price_usd": 191.45,
      "fee_usd": 0.50,
      "executed_at": "2026-04-18T10:21:00Z"
    },
    {
      "symbol": "NVDA",
      "side": "buy",
      "quantity": 1.40,
      "price_usd": 938.20,
      "fee_usd": 0.60
    }
  ]
}
```

Response:

```json
{
  "clerk_user_id": "user_2w7abc...",
  "account_id": "5f4e6e6f-...",
  "account_name": "Raenest US Stocks",
  "trades_applied": 2,
  "positions_touched": 2,
  "account_cash_balance_usd": -1931.13,
  "estimated_account_value_usd": 1930.74,
  "estimated_account_value_ngn": 2973485.73
}
```

## 2) Fetch Raenest portfolio intelligence

`GET /api/raenest/portfolio-intelligence/{clerk_user_id}?fx_rate_ngn_per_usd=1540.25`

Headers:

```http
x-raenest-api-key: <RAENEST_API_KEY>
```

Response includes:

- `total_cash_usd`
- `total_market_value_usd`
- `total_portfolio_value_usd`
- `top_holdings`
- `sector_exposure`
- `concentration_flags`
- optional NGN mirrors

## 3) Trigger AI analysis remotely

`POST /api/raenest/trigger-analysis`

Headers:

```http
x-raenest-api-key: <RAENEST_API_KEY>
Content-Type: application/json
```

Request:

```json
{
  "clerk_user_id": "user_2w7abc...",
  "analysis_type": "portfolio_analysis",
  "options": {
    "priority": "high",
    "source": "raenest_trade_sync",
    "focus": ["concentration", "regional_exposure", "retirement_readiness"]
  }
}
```

Response:

```json
{
  "job_id": "0f16d9d9-...",
  "message": "Raenest analysis started. Poll /api/jobs/{job_id} for status/results."
}
```

---

## Why This Is Highly Relevant to Raenest

This upgrade turns Alex from a generic AI portfolio tool into a **Raenest monetizable intelligence module**:

1. **Post-trade intelligence** for newly launched US shares feature
2. **Cross-border value framing** with USD + NGN views
3. **Risk alerts** (concentration and sector skew) for better user outcomes
4. **Backend-first integration** (no frontend rewrite required)
5. **Scalable AI orchestration** via existing Alex queue/agent stack

---

## Integration Pattern in Raenest

Recommended sequence:

1. User executes trade in Raenest app
2. Raenest backend calls `sync-trades`
3. Raenest backend calls `trigger-analysis`
4. Raenest backend polls `/api/jobs/{job_id}`
5. UI surfaces recommendations, chart insights, and retirement impact

---

## Security and Compliance Notes

1. Keep `RAENEST_API_KEY` server-side only
2. Rotate key regularly
3. Restrict endpoint access to Raenest trusted infrastructure
4. Add request signing/JWT service auth as a next hardening step

---

## Files Updated

1. `backend/api/main.py`
2. `.env.example`

---

## Recommended Next Commercial Enhancements

1. Add KYC tier-aware risk guardrails
2. Add real-time quote reconciliation against broker fills
3. Add webhook callbacks back to Raenest for completed AI jobs
4. Add portfolio health score and nudges for engagement loops
5. Add premium user segmentation for upsell analytics

