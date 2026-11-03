"""Dashboard endpoints."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import authenticate_request as get_current_user
from app.models.auth import AuthenticatedUser
from app.services.cache import get_revenue_summary
from app.services.reservations import PropertyNotFoundError, RevenueCurrencyError

router = APIRouter()


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str = Query(..., min_length=1),
    month: int | None = Query(None, ge=1, le=12),
    year: int | None = Query(None, ge=1, le=9998),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the current user's tenant-scoped dashboard summary."""
    tenant_id = current_user.tenant_id
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A tenant context is required",
        )
    if (month is None) != (year is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="month and year must be provided together",
        )

    try:
        revenue_data = await get_revenue_summary(
            property_id, tenant_id, month=month, year=year
        )
    except PropertyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except RevenueCurrencyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    total = Decimal(str(revenue_data["total"])).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {
        "property_id": revenue_data["property_id"],
        "total_revenue": format(total, ".2f"),
        "currency": revenue_data["currency"],
        "reservations_count": int(revenue_data["count"]),
        "month": revenue_data.get("month"),
        "year": revenue_data.get("year"),
    }
