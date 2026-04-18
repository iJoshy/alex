"""
FastAPI backend for Alex Financial Advisor
Handles all API routes with Clerk JWT authentication
"""

import os
import json
import logging
import time
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from decimal import Decimal
import uuid
from collections import defaultdict

from fastapi import FastAPI, HTTPException, Depends, status, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
import boto3
from mangum import Mangum
from dotenv import load_dotenv
from fastapi_clerk_auth import ClerkConfig, ClerkHTTPBearer, HTTPAuthorizationCredentials

from src import Database
from src.schemas import (
    UserCreate,
    AccountCreate,
    PositionCreate,
    JobCreate, JobUpdate,
    JobType, JobStatus
)

# Load environment variables
load_dotenv(override=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Alex Financial Advisor API",
    description="Backend API for AI-powered financial planning",
    version="1.0.0"
)


def _request_id_from_request(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")

# CORS configuration
# Get origins from CORS_ORIGINS env var (comma-separated) or fall back to localhost
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_context(request: Request, call_next):
    """
    Add request_id tracing and simple latency logging for operational handover.
    """
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    response.headers["x-request-id"] = request_id
    logger.info(
        json.dumps(
            {
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": elapsed_ms,
            }
        )
    )
    return response

# Custom exception handlers for better error messages
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors with user-friendly messages"""
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Invalid input data. Please check your request and try again.",
            "request_id": _request_id_from_request(request),
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with improved messages"""
    # Map technical errors to user-friendly messages
    user_friendly_messages = {
        401: "Your session has expired. Please sign in again.",
        403: "You don't have permission to access this resource.",
        404: "The requested resource was not found.",
        429: "Too many requests. Please slow down and try again later.",
        500: "An internal error occurred. Please try again later.",
        503: "The service is temporarily unavailable. Please try again later."
    }

    message = user_friendly_messages.get(exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": message, "request_id": _request_id_from_request(request)}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected errors gracefully"""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred. Our team has been notified.",
            "request_id": _request_id_from_request(request),
        }
    )

# Initialize services
db = Database()

# SQS client for job queueing
sqs_client = boto3.client('sqs', region_name=os.getenv('DEFAULT_AWS_REGION', 'us-east-1'))
SQS_QUEUE_URL = os.getenv('SQS_QUEUE_URL', '')
RAENEST_API_KEY = os.getenv('RAENEST_API_KEY', '')

# Clerk authentication setup (exactly like saas reference)
clerk_config = ClerkConfig(jwks_url=os.getenv("CLERK_JWKS_URL"))
clerk_guard = ClerkHTTPBearer(clerk_config)

async def get_current_user_id(creds: HTTPAuthorizationCredentials = Depends(clerk_guard)) -> str:
    """Extract user ID from validated Clerk token"""
    # The clerk_guard dependency already validated the token
    # creds.decoded contains the JWT payload
    user_id = creds.decoded["sub"]
    logger.info(f"Authenticated user: {user_id}")
    return user_id


async def require_raenest_api_key(
    x_raenest_api_key: Optional[str] = Header(default=None, alias="x-raenest-api-key")
) -> bool:
    """Simple server-to-server guard for Raenest integration endpoints."""
    if not RAENEST_API_KEY:
        logger.error("RAENEST_API_KEY is not configured")
        raise HTTPException(status_code=503, detail="Raenest integration is not configured")

    if x_raenest_api_key != RAENEST_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid Raenest API key")

    return True


def _ensure_raenest_user(clerk_user_id: str) -> Dict[str, Any]:
    """Ensure a user exists for external integration flow."""
    user = db.users.find_by_clerk_id(clerk_user_id)
    if user:
        return user

    placeholder_name = f"Raenest User {clerk_user_id[-6:]}" if len(clerk_user_id) >= 6 else "Raenest User"
    user_data = {
        "clerk_user_id": clerk_user_id,
        "display_name": placeholder_name,
        "years_until_retirement": 20,
        "target_retirement_income": 60000,
        "asset_class_targets": {"equity": 80, "fixed_income": 20},
        "region_targets": {"north_america": 70, "international": 30},
    }
    db.users.db.insert("users", user_data, returning="clerk_user_id")
    logger.info("Created integration user for clerk_user_id=%s", clerk_user_id)
    return db.users.find_by_clerk_id(clerk_user_id)


def _get_or_create_account_for_user(clerk_user_id: str, account_name: str, base_currency: str) -> Dict[str, Any]:
    """Find existing account by name or create a new one."""
    user_accounts = db.accounts.find_by_user(clerk_user_id)
    normalized_name = account_name.strip().lower()
    for account in user_accounts:
        if account.get("account_name", "").strip().lower() == normalized_name:
            return account

    account_purpose = (
        f"Auto-synced Raenest {base_currency} account for US share trading and AI insights"
    )
    account_id = db.accounts.create_account(
        clerk_user_id=clerk_user_id,
        account_name=account_name,
        account_purpose=account_purpose,
        cash_balance=Decimal("0"),
    )
    return db.accounts.find_by_id(account_id)


def _ensure_instrument_exists(symbol: str) -> None:
    """Create a minimal instrument placeholder for newly traded US stocks."""
    symbol = symbol.upper().strip()
    if db.instruments.find_by_symbol(symbol):
        return

    from src.schemas import InstrumentCreate

    instrument_data = InstrumentCreate(
        symbol=symbol,
        name=f"{symbol} - Raenest Imported",
        instrument_type="stock",
        current_price=Decimal("0"),
        allocation_regions={"north_america": 100},
        allocation_sectors={"other": 100},
        allocation_asset_class={"equity": 100},
    )
    db.instruments.create_instrument(instrument_data)
    logger.info("Created instrument placeholder for %s", symbol)


def _compute_portfolio_intelligence(
    clerk_user_id: str, fx_rate_ngn_per_usd: Optional[Decimal] = None
) -> Dict[str, Any]:
    """Build an integration-friendly portfolio intelligence snapshot."""
    user_accounts = db.accounts.find_by_user(clerk_user_id)
    total_cash_usd = Decimal("0")
    total_market_value_usd = Decimal("0")
    holdings: List[Dict[str, Any]] = []
    sector_bucket: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for account in user_accounts:
        account_id = account["id"]
        total_cash_usd += Decimal(str(account.get("cash_balance") or 0))

        positions = db.positions.find_by_account(account_id)
        for pos in positions:
            symbol = pos["symbol"]
            quantity = Decimal(str(pos.get("quantity") or 0))
            instrument = db.instruments.find_by_symbol(symbol) or {}
            current_price = Decimal(str(instrument.get("current_price") or 0))
            market_value = quantity * current_price
            total_market_value_usd += market_value

            holdings.append(
                {
                    "account_id": account_id,
                    "symbol": symbol,
                    "quantity": float(quantity),
                    "price_usd": float(current_price),
                    "market_value_usd": float(market_value),
                }
            )

            for sector, pct in (instrument.get("allocation_sectors") or {}).items():
                sector_bucket[sector] += market_value * (Decimal(str(pct)) / Decimal("100"))

    holdings.sort(key=lambda x: x["market_value_usd"], reverse=True)
    top_holdings = holdings[:5]

    total_portfolio_usd = total_cash_usd + total_market_value_usd
    sector_exposure = []
    if total_market_value_usd > 0:
        for sector, value in sector_bucket.items():
            sector_exposure.append(
                {
                    "sector": sector,
                    "weight_pct": float((value / total_market_value_usd) * Decimal("100")),
                }
            )
        sector_exposure.sort(key=lambda x: x["weight_pct"], reverse=True)

    concentration_flags = []
    if total_market_value_usd > 0:
        for holding in top_holdings:
            weight = Decimal(str(holding["market_value_usd"])) / total_market_value_usd
            if weight >= Decimal("0.25"):
                concentration_flags.append(
                    {
                        "symbol": holding["symbol"],
                        "weight_pct": float(weight * Decimal("100")),
                        "message": "Position exceeds 25% concentration threshold",
                    }
                )

    response = {
        "clerk_user_id": clerk_user_id,
        "accounts": len(user_accounts),
        "total_cash_usd": float(total_cash_usd),
        "total_market_value_usd": float(total_market_value_usd),
        "total_portfolio_value_usd": float(total_portfolio_usd),
        "top_holdings": top_holdings,
        "sector_exposure": sector_exposure,
        "concentration_flags": concentration_flags,
    }

    if fx_rate_ngn_per_usd and fx_rate_ngn_per_usd > 0:
        rate = Decimal(str(fx_rate_ngn_per_usd))
        response["fx_rate_ngn_per_usd"] = float(rate)
        response["total_portfolio_value_ngn"] = float(total_portfolio_usd * rate)
        response["total_market_value_ngn"] = float(total_market_value_usd * rate)
        response["total_cash_ngn"] = float(total_cash_usd * rate)

    return response

# Request/Response models
class UserResponse(BaseModel):
    user: Dict[str, Any]
    created: bool

class UserUpdate(BaseModel):
    """Update user settings"""
    display_name: Optional[str] = None
    years_until_retirement: Optional[int] = None
    target_retirement_income: Optional[float] = None
    asset_class_targets: Optional[Dict[str, float]] = None
    region_targets: Optional[Dict[str, float]] = None

class AccountUpdate(BaseModel):
    """Update account"""
    account_name: Optional[str] = None
    account_purpose: Optional[str] = None
    cash_balance: Optional[float] = None

class PositionUpdate(BaseModel):
    """Update position"""
    quantity: Optional[float] = None

class AnalyzeRequest(BaseModel):
    analysis_type: str = Field(default="portfolio", description="Type of analysis to perform")
    options: Dict[str, Any] = Field(default_factory=dict, description="Analysis options")

class AnalyzeResponse(BaseModel):
    job_id: str
    message: str

TradeSide = Literal["buy", "sell"]


class RaenestTrade(BaseModel):
    """Represents a settled trade event from Raenest."""

    symbol: str = Field(..., min_length=1, max_length=20, description="US stock ticker")
    side: TradeSide
    quantity: Decimal = Field(..., gt=0, description="Executed share quantity")
    price_usd: Decimal = Field(..., ge=0, description="Execution price in USD")
    fee_usd: Decimal = Field(default=Decimal("0"), ge=0, description="Execution fee in USD")
    executed_at: Optional[str] = Field(
        default=None, description="Trade execution timestamp in ISO-8601 format"
    )


class RaenestTradeSyncRequest(BaseModel):
    """Batch trade sync payload for Raenest -> Alex."""

    clerk_user_id: str = Field(..., description="Mapped user id in Alex/Clerk")
    account_name: str = Field(
        default="Raenest US Stocks",
        description="Target account in Alex where trades should be reflected",
    )
    base_currency: Literal["NGN", "USD"] = Field(default="NGN")
    fx_rate_ngn_per_usd: Optional[Decimal] = Field(
        default=None, ge=0, description="Optional FX conversion rate used by Raenest"
    )
    trades: List[RaenestTrade] = Field(
        ..., min_length=1, description="List of trade events to apply in order"
    )


class RaenestTradeSyncResponse(BaseModel):
    """Response after applying trade events."""

    clerk_user_id: str
    account_id: str
    account_name: str
    trades_applied: int
    positions_touched: int
    account_cash_balance_usd: float
    estimated_account_value_usd: float
    estimated_account_value_ngn: Optional[float] = None


class RaenestAnalysisTriggerRequest(BaseModel):
    """Trigger AI analysis for a user after sync/events."""

    clerk_user_id: str
    analysis_type: str = Field(default="portfolio_analysis")
    options: Dict[str, Any] = Field(default_factory=dict)

# API Routes

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/ops/readiness")
async def readiness_check():
    """
    Operational readiness snapshot for handover teams.
    Returns only boolean config state (no secrets).
    """
    checks = {
        "aurora_cluster_arn_configured": bool(os.getenv("AURORA_CLUSTER_ARN")),
        "aurora_secret_arn_configured": bool(os.getenv("AURORA_SECRET_ARN")),
        "sqs_queue_configured": bool(SQS_QUEUE_URL),
        "clerk_jwks_configured": bool(os.getenv("CLERK_JWKS_URL")),
        "raenest_api_key_configured": bool(RAENEST_API_KEY),
    }
    overall = all(checks.values())
    return {
        "status": "ready" if overall else "degraded",
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
    }

@app.get("/api/user", response_model=UserResponse)
async def get_or_create_user(
    clerk_user_id: str = Depends(get_current_user_id),
    creds: HTTPAuthorizationCredentials = Depends(clerk_guard)
):
    """Get user or create if first time"""

    try:
        # Check if user exists
        user = db.users.find_by_clerk_id(clerk_user_id)

        if user:
            return UserResponse(user=user, created=False)

        # Create new user with defaults from JWT token
        token_data = creds.decoded
        display_name = token_data.get('name') or token_data.get('email', '').split('@')[0] or "New User"

        # Create user with ALL defaults in one operation
        user_data = {
            'clerk_user_id': clerk_user_id,
            'display_name': display_name,
            'years_until_retirement': 20,
            'target_retirement_income': 60000,
            'asset_class_targets': {"equity": 70, "fixed_income": 30},
            'region_targets': {"north_america": 50, "international": 50}
        }

        # Insert directly with all data
        created_clerk_id = db.users.db.insert('users', user_data, returning='clerk_user_id')

        # Fetch the created user
        created_user = db.users.find_by_clerk_id(clerk_user_id)
        logger.info(f"Created new user: {clerk_user_id}")

        return UserResponse(user=created_user, created=True)

    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        raise HTTPException(status_code=500, detail="Failed to load user profile")

@app.put("/api/user")
async def update_user(user_update: UserUpdate, clerk_user_id: str = Depends(get_current_user_id)):
    """Update user settings"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Update user - users table uses clerk_user_id as primary key
        update_data = user_update.model_dump(exclude_unset=True)

        # Use the database client directly since users table has clerk_user_id as PK
        db.users.db.update(
            'users',
            update_data,
            "clerk_user_id = :clerk_user_id",
            {'clerk_user_id': clerk_user_id}
        )

        # Return updated user
        updated_user = db.users.find_by_clerk_id(clerk_user_id)
        return updated_user

    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts")
async def list_accounts(clerk_user_id: str = Depends(get_current_user_id)):
    """List user's accounts"""

    try:
        # Get accounts for user
        accounts = db.accounts.find_by_user(clerk_user_id)
        return accounts

    except Exception as e:
        logger.error(f"Error listing accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/accounts")
async def create_account(account: AccountCreate, clerk_user_id: str = Depends(get_current_user_id)):
    """Create new account"""

    try:
        # Verify user exists
        user = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Create account
        account_id = db.accounts.create_account(
            clerk_user_id=clerk_user_id,
            account_name=account.account_name,
            account_purpose=account.account_purpose,
            cash_balance=getattr(account, 'cash_balance', Decimal('0'))
        )

        # Return created account
        created_account = db.accounts.find_by_id(account_id)
        return created_account

    except Exception as e:
        logger.error(f"Error creating account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/accounts/{account_id}")
async def update_account(account_id: str, account_update: AccountUpdate, clerk_user_id: str = Depends(get_current_user_id)):
    """Update account"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Update account
        update_data = account_update.model_dump(exclude_unset=True)
        db.accounts.update(account_id, update_data)

        # Return updated account
        updated_account = db.accounts.find_by_id(account_id)
        return updated_account

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Delete an account and all its positions"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Delete all positions first (due to foreign key constraint)
        positions = db.positions.find_by_account(account_id)
        for position in positions:
            db.positions.delete(position['id'])

        # Delete the account
        db.accounts.delete(account_id)

        return {"message": "Account deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accounts/{account_id}/positions")
async def list_positions(account_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Get positions for account"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        positions = db.positions.find_by_account(account_id)

        # Format positions with instrument data for frontend
        formatted_positions = []
        for pos in positions:
            # Get full instrument data
            instrument = db.instruments.find_by_symbol(pos['symbol'])
            formatted_positions.append({
                **pos,
                'instrument': instrument
            })

        return {"positions": formatted_positions}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing positions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/positions")
async def create_position(position: PositionCreate, clerk_user_id: str = Depends(get_current_user_id)):
    """Create position"""

    try:
        # Verify account belongs to user
        account = db.accounts.find_by_id(position.account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Check if instrument exists, if not create it
        instrument = db.instruments.find_by_symbol(position.symbol.upper())
        if not instrument:
            logger.info(f"Creating new instrument: {position.symbol.upper()}")
            # Create a basic instrument entry with default allocations
            # Import the schema from database
            from src.schemas import InstrumentCreate

            # Determine type based on common patterns
            symbol_upper = position.symbol.upper()
            if len(symbol_upper) <= 5 and symbol_upper.isalpha():
                instrument_type = "stock"
            else:
                instrument_type = "etf"

            # Create instrument with basic default allocations
            # These can be updated later by the tagger agent
            new_instrument = InstrumentCreate(
                symbol=symbol_upper,
                name=f"{symbol_upper} - User Added",  # Basic name, can be updated later
                instrument_type=instrument_type,
                current_price=Decimal("0.00"),  # Price will be updated by background processes
                allocation_regions={"north_america": 100.0},  # Default to 100% NA
                allocation_sectors={"other": 100.0},  # Default to 100% other
                allocation_asset_class={"equity": 100.0} if instrument_type == "stock" else {"fixed_income": 100.0}
            )

            db.instruments.create_instrument(new_instrument)

        # Add position
        position_id = db.positions.add_position(
            account_id=position.account_id,
            symbol=position.symbol.upper(),
            quantity=position.quantity
        )

        # Return created position
        created_position = db.positions.find_by_id(position_id)
        return created_position

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating position: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/positions/{position_id}")
async def update_position(position_id: str, position_update: PositionUpdate, clerk_user_id: str = Depends(get_current_user_id)):
    """Update position"""

    try:
        # Get position and verify ownership
        position = db.positions.find_by_id(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        account = db.accounts.find_by_id(position['account_id'])
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Update position
        update_data = position_update.model_dump(exclude_unset=True)
        db.positions.update(position_id, update_data)

        # Return updated position
        updated_position = db.positions.find_by_id(position_id)
        return updated_position

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating position: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/positions/{position_id}")
async def delete_position(position_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Delete position"""

    try:
        # Get position and verify ownership
        position = db.positions.find_by_id(position_id)
        if not position:
            raise HTTPException(status_code=404, detail="Position not found")

        account = db.accounts.find_by_id(position['account_id'])
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        # Verify ownership - accounts table stores clerk_user_id directly
        if account.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        db.positions.delete(position_id)
        return {"message": "Position deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting position: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/instruments")
async def list_instruments(clerk_user_id: str = Depends(get_current_user_id)):
    """Get all available instruments for autocomplete"""

    try:
        instruments = db.instruments.find_all()
        # Return simplified list for autocomplete
        return [
            {
                "symbol": inst["symbol"],
                "name": inst["name"],
                "instrument_type": inst["instrument_type"],
                "current_price": float(inst["current_price"]) if inst.get("current_price") else None
            }
            for inst in instruments
        ]
    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/analyze", response_model=AnalyzeResponse)
async def trigger_analysis(request: AnalyzeRequest, clerk_user_id: str = Depends(get_current_user_id)):
    """Trigger portfolio analysis"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Create job
        job_id = db.jobs.create_job(
            clerk_user_id=clerk_user_id,
            job_type="portfolio_analysis",
            request_payload=request.model_dump()
        )

        # Get the created job
        job = db.jobs.find_by_id(job_id)

        # Send to SQS
        if SQS_QUEUE_URL:
            message = {
                'job_id': str(job_id),
                'clerk_user_id': clerk_user_id,
                'analysis_type': request.analysis_type,
                'options': request.options
            }

            sqs_client.send_message(
                QueueUrl=SQS_QUEUE_URL,
                MessageBody=json.dumps(message)
            )
            logger.info(f"Sent analysis job to SQS: {job_id}")
        else:
            logger.warning("SQS_QUEUE_URL not configured, job created but not queued")

        return AnalyzeResponse(
            job_id=str(job_id),
            message="Analysis started. Check job status for results."
        )

    except Exception as e:
        logger.error(f"Error triggering analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/raenest/sync-trades", response_model=RaenestTradeSyncResponse)
async def raenest_sync_trades(
    request: RaenestTradeSyncRequest, _authorized: bool = Depends(require_raenest_api_key)
):
    """
    Server-to-server endpoint for Raenest trade sync.
    Applies buy/sell trades to positions, keeps cash in sync, and returns updated account snapshot.
    """
    try:
        _ensure_raenest_user(request.clerk_user_id)
        account = _get_or_create_account_for_user(
            clerk_user_id=request.clerk_user_id,
            account_name=request.account_name,
            base_currency=request.base_currency,
        )
        account_id = account["id"]

        # Build mutable position map for deterministic trade application
        current_positions = db.positions.find_by_account(account_id)
        position_map: Dict[str, Dict[str, Any]] = {
            p["symbol"].upper(): p for p in current_positions
        }

        cash_balance = Decimal(str(account.get("cash_balance") or 0))
        touched_symbols = set()

        for trade in request.trades:
            symbol = trade.symbol.upper().strip()
            _ensure_instrument_exists(symbol)
            touched_symbols.add(symbol)

            quantity = Decimal(str(trade.quantity))
            price_usd = Decimal(str(trade.price_usd))
            fee_usd = Decimal(str(trade.fee_usd or 0))
            delta = quantity if trade.side == "buy" else -quantity

            existing = position_map.get(symbol)
            current_qty = Decimal(str(existing.get("quantity") if existing else 0))
            updated_qty = current_qty + delta

            if updated_qty < 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid sell quantity for {symbol}: position would go negative",
                )

            # Cash movement based on executed trade
            gross = quantity * price_usd
            if trade.side == "buy":
                cash_balance -= gross + fee_usd
            else:
                cash_balance += gross - fee_usd

            if updated_qty == 0 and existing:
                db.positions.delete(existing["id"])
                position_map.pop(symbol, None)
                continue

            db.positions.add_position(account_id=account_id, symbol=symbol, quantity=updated_qty)
            refreshed_positions = db.positions.find_by_account(account_id)
            refreshed_map = {p["symbol"].upper(): p for p in refreshed_positions}
            position_map = refreshed_map

        db.accounts.update(account_id, {"cash_balance": cash_balance})
        portfolio_value = db.positions.get_portfolio_value(account_id)

        response = RaenestTradeSyncResponse(
            clerk_user_id=request.clerk_user_id,
            account_id=str(account_id),
            account_name=account["account_name"],
            trades_applied=len(request.trades),
            positions_touched=len(touched_symbols),
            account_cash_balance_usd=float(cash_balance),
            estimated_account_value_usd=portfolio_value.get("total_value", 0.0),
            estimated_account_value_ngn=(
                float(Decimal(str(portfolio_value.get("total_value", 0.0))) * request.fx_rate_ngn_per_usd)
                if request.fx_rate_ngn_per_usd and request.fx_rate_ngn_per_usd > 0
                else None
            ),
        )
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing Raenest trades: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to sync Raenest trades")


@app.get("/api/raenest/portfolio-intelligence/{clerk_user_id}")
async def raenest_portfolio_intelligence(
    clerk_user_id: str,
    fx_rate_ngn_per_usd: Optional[Decimal] = None,
    _authorized: bool = Depends(require_raenest_api_key),
):
    """
    Integration-friendly snapshot for Raenest UI:
    portfolio value, top holdings, sector exposure, and concentration alerts.
    """
    try:
        user = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return _compute_portfolio_intelligence(
            clerk_user_id=clerk_user_id,
            fx_rate_ngn_per_usd=fx_rate_ngn_per_usd,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error building Raenest portfolio intelligence: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to build portfolio intelligence")


@app.post("/api/raenest/trigger-analysis", response_model=AnalyzeResponse)
async def raenest_trigger_analysis(
    request: RaenestAnalysisTriggerRequest, _authorized: bool = Depends(require_raenest_api_key)
):
    """
    Server-to-server analysis trigger for Raenest orchestration.
    Creates a job and pushes it to SQS for planner execution.
    """
    try:
        user = db.users.find_by_clerk_id(request.clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        job_id = db.jobs.create_job(
            clerk_user_id=request.clerk_user_id,
            job_type="portfolio_analysis",
            request_payload={
                "analysis_type": request.analysis_type,
                "options": request.options,
                "source": "raenest_integration",
                "triggered_at": datetime.now().isoformat(),
            },
        )

        if SQS_QUEUE_URL:
            message = {
                "job_id": str(job_id),
                "clerk_user_id": request.clerk_user_id,
                "analysis_type": request.analysis_type,
                "options": request.options,
                "source": "raenest_integration",
            }
            sqs_client.send_message(QueueUrl=SQS_QUEUE_URL, MessageBody=json.dumps(message))
            logger.info(f"Sent Raenest analysis job to SQS: {job_id}")
        else:
            logger.warning("SQS_QUEUE_URL not configured, Raenest analysis job not queued")

        return AnalyzeResponse(
            job_id=str(job_id),
            message="Raenest analysis started. Poll /api/jobs/{job_id} for status/results.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering Raenest analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to trigger Raenest analysis")

@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str, clerk_user_id: str = Depends(get_current_user_id)):
    """Get job status and results"""

    try:
        # Get job
        job = db.jobs.find_by_id(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Verify job belongs to user - jobs table stores clerk_user_id directly
        if job.get('clerk_user_id') != clerk_user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        return job

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/jobs")
async def list_jobs(clerk_user_id: str = Depends(get_current_user_id)):
    """List user's analysis jobs"""

    try:
        # Get jobs for this user (with higher limit to avoid missing recent jobs)
        user_jobs = db.jobs.find_by_user(clerk_user_id, limit=100)
        # Sort by created_at descending (most recent first)
        user_jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return {"jobs": user_jobs}

    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/reset-accounts")
async def reset_accounts(clerk_user_id: str = Depends(get_current_user_id)):
    """Delete all accounts for the current user"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get all accounts for user
        accounts = db.accounts.find_by_user(clerk_user_id)

        # Delete each account (positions will cascade delete)
        deleted_count = 0
        for account in accounts:
            try:
                # Positions are deleted automatically via CASCADE
                db.accounts.delete(account['id'])
                deleted_count += 1
            except Exception as e:
                logger.warning(f"Could not delete account {account['id']}: {e}")

        return {
            "message": f"Deleted {deleted_count} account(s)",
            "accounts_deleted": deleted_count
        }

    except Exception as e:
        logger.error(f"Error resetting accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/populate-test-data")
async def populate_test_data(clerk_user_id: str = Depends(get_current_user_id)):
    """Populate test data for the current user"""

    try:
        # Get user
        user = db.users.find_by_clerk_id(clerk_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Define missing instruments that might not be in the database
        missing_instruments = {
            "AAPL": {
                "name": "Apple Inc.",
                "type": "stock",
                "current_price": 195.89,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "AMZN": {
                "name": "Amazon.com Inc.",
                "type": "stock",
                "current_price": 178.35,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"consumer_discretionary": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "NVDA": {
                "name": "NVIDIA Corporation",
                "type": "stock",
                "current_price": 522.74,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "MSFT": {
                "name": "Microsoft Corporation",
                "type": "stock",
                "current_price": 430.82,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100}
            },
            "GOOGL": {
                "name": "Alphabet Inc. Class A",
                "type": "stock",
                "current_price": 173.69,
                "allocation_regions": {"north_america": 100},
                "allocation_sectors": {"technology": 100},
                "allocation_asset_class": {"equity": 100}
            },
        }

        # Check and add missing instruments
        for symbol, info in missing_instruments.items():
            existing = db.instruments.find_by_symbol(symbol)
            if not existing:
                try:
                    from src.schemas import InstrumentCreate

                    instrument_data = InstrumentCreate(
                        symbol=symbol,
                        name=info["name"],
                        instrument_type=info["type"],
                        current_price=Decimal(str(info["current_price"])),
                        allocation_regions=info["allocation_regions"],
                        allocation_sectors=info["allocation_sectors"],
                        allocation_asset_class=info["allocation_asset_class"]
                    )
                    db.instruments.create_instrument(instrument_data)
                    logger.info(f"Added missing instrument: {symbol}")
                except Exception as e:
                    logger.warning(f"Could not add instrument {symbol}: {e}")

        # Create accounts with test data
        accounts_data = [
            {
                "name": "401k Long-term",
                "purpose": "Primary retirement savings account with employer match",
                "cash": 5000.00,
                "positions": [
                    ("SPY", 150),   # S&P 500 ETF
                    ("VTI", 100),   # Total Stock Market ETF
                    ("BND", 200),   # Bond ETF
                    ("QQQ", 75),    # Nasdaq ETF
                    ("IWM", 50),    # Small Cap ETF
                ]
            },
            {
                "name": "Roth IRA",
                "purpose": "Tax-free retirement growth account",
                "cash": 2500.00,
                "positions": [
                    ("VTI", 80),    # Total Stock Market ETF
                    ("VXUS", 60),   # International Stock ETF
                    ("VNQ", 40),    # Real Estate ETF
                    ("GLD", 25),    # Gold ETF
                    ("TLT", 30),    # Long-term Treasury ETF
                    ("VIG", 45),    # Dividend Growth ETF
                ]
            },
            {
                "name": "Brokerage Account",
                "purpose": "Taxable investment account for individual stocks",
                "cash": 10000.00,
                "positions": [
                    ("TSLA", 15),   # Tesla
                    ("AAPL", 50),   # Apple
                    ("AMZN", 10),   # Amazon
                    ("NVDA", 25),   # Nvidia
                    ("MSFT", 30),   # Microsoft
                    ("GOOGL", 20),  # Google
                ]
            }
        ]

        created_accounts = []
        for account_data in accounts_data:
            # Create account
            account_id = db.accounts.create_account(
                clerk_user_id=clerk_user_id,
                account_name=account_data["name"],
                account_purpose=account_data["purpose"],
                cash_balance=Decimal(str(account_data["cash"]))
            )

            # Add positions
            for symbol, quantity in account_data["positions"]:
                try:
                    db.positions.add_position(
                        account_id=account_id,
                        symbol=symbol,
                        quantity=Decimal(str(quantity))
                    )
                except Exception as e:
                    logger.warning(f"Could not add position {symbol}: {e}")

            created_accounts.append(account_id)

        # Get all accounts with their positions for summary
        all_accounts = []
        for account_id in created_accounts:
            account = db.accounts.find_by_id(account_id)
            positions = db.positions.find_by_account(account_id)
            account['positions'] = positions
            all_accounts.append(account)

        return {
            "message": "Test data populated successfully",
            "accounts_created": len(created_accounts),
            "accounts": all_accounts
        }

    except Exception as e:
        logger.error(f"Error populating test data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Lambda handler
handler = Mangum(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
