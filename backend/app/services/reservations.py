"""Reservation-related financial calculations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import text

from app.core.database_pool import db_pool

_CENT = Decimal("0.01")


class RevenueCurrencyError(ValueError):
    """Raised when a report would combine amounts from different currencies."""


class PropertyNotFoundError(LookupError):
    """Raised when a property does not belong to the requested tenant."""


def _validate_period(month: int | None, year: int | None) -> None:
    if month is not None and not 1 <= month <= 12:
        raise ValueError("month must be between 1 and 12")
    if year is not None and not 1 <= year <= 9998:
        raise ValueError("year must be between 1 and 9998")
    if (month is None) != (year is None):
        raise ValueError("month and year must be provided together")


def _period_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


async def calculate_monthly_revenue(
    property_id: str,
    month: int,
    year: int,
    db_session: Any | None = None,
    tenant_id: str | None = None,
) -> Decimal:
    """Calculate revenue for a property and local calendar month.

    A database session and tenant ID are required. This function deliberately
    does not return placeholder values when the database is unavailable.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    _validate_period(month, year)
    start_local, end_local = _period_bounds(year, month)

    query = text(
        """
        SELECT COALESCE(SUM(r.total_amount), 0) AS total_revenue,
               COUNT(DISTINCT r.currency) AS currency_count
        FROM reservations AS r
        JOIN properties AS p
          ON p.id = r.property_id AND p.tenant_id = r.tenant_id
        WHERE r.property_id = :property_id
          AND r.tenant_id = :tenant_id
          AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_local
          AND (r.check_in_date AT TIME ZONE p.timezone) < :end_local
        """
    )

    if db_session is not None:
        result = await db_session.execute(query, {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "start_local": start_local,
            "end_local": end_local,
        })
        row = result.fetchone()
    else:
        if db_pool.session_factory is None:
            await db_pool.initialize()
        async with db_pool.get_session() as session:
            result = await session.execute(query, {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_local": start_local,
                "end_local": end_local,
            })
            row = result.fetchone()

    if row and row.currency_count > 1:
        raise RevenueCurrencyError(
            "Revenue cannot be aggregated across multiple currencies"
        )
    return Decimal(str(row.total_revenue if row else 0)).quantize(
        _CENT, rounding=ROUND_HALF_UP
    )


async def calculate_total_revenue(
    property_id: str,
    tenant_id: str,
    month: int | None = None,
    year: int | None = None,
) -> dict[str, Any]:
    """Return a tenant-scoped revenue summary for one calendar month.

    When no period is supplied, the latest month containing a reservation is
    selected. Database failures propagate to the API layer; they are never
    disguised as successful financial results.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required")
    _validate_period(month, year)

    if db_pool.session_factory is None:
        await db_pool.initialize()
    if db_pool.session_factory is None:
        raise RuntimeError("Database connection pool is unavailable")

    async with db_pool.get_session() as session:
        property_result = await session.execute(
            text("SELECT 1 FROM properties WHERE id = :property_id AND tenant_id = :tenant_id"),
            {"property_id": property_id, "tenant_id": tenant_id},
        )
        if property_result.fetchone() is None:
            raise PropertyNotFoundError("Property was not found")

        target_month, target_year = month, year
        if target_month is None:
            latest_period_query = text(
                """
                SELECT EXTRACT(MONTH FROM local_check_in)::int AS latest_month,
                       EXTRACT(YEAR FROM local_check_in)::int AS latest_year
                FROM (
                    SELECT r.check_in_date AT TIME ZONE p.timezone AS local_check_in
                    FROM reservations AS r
                    JOIN properties AS p
                      ON p.id = r.property_id AND p.tenant_id = r.tenant_id
                    WHERE r.property_id = :property_id
                      AND r.tenant_id = :tenant_id
                    ORDER BY local_check_in DESC
                    LIMIT 1
                ) AS latest
                """
            )
            latest_result = await session.execute(latest_period_query, {
                "property_id": property_id,
                "tenant_id": tenant_id,
            })
            latest = latest_result.fetchone()
            if latest is None:
                return {
                    "property_id": property_id,
                    "tenant_id": tenant_id,
                    "total": "0.00",
                    "currency": "USD",
                    "count": 0,
                    "month": None,
                    "year": None,
                }
            target_month, target_year = int(latest.latest_month), int(latest.latest_year)

        assert target_month is not None and target_year is not None
        start_local, end_local = _period_bounds(target_year, target_month)
        summary_query = text(
            """
            SELECT COALESCE(SUM(r.total_amount), 0) AS total_revenue,
                   COUNT(*) AS reservation_count,
                   COUNT(DISTINCT r.currency) AS currency_count,
                   MIN(r.currency) AS currency
            FROM reservations AS r
            JOIN properties AS p
              ON p.id = r.property_id AND p.tenant_id = r.tenant_id
            WHERE r.property_id = :property_id
              AND r.tenant_id = :tenant_id
              AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_local
              AND (r.check_in_date AT TIME ZONE p.timezone) < :end_local
            """
        )
        result = await session.execute(summary_query, {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "start_local": start_local,
            "end_local": end_local,
        })
        row = result.fetchone()

        if row and row.currency_count > 1:
            raise RevenueCurrencyError(
                "Revenue cannot be aggregated across multiple currencies"
            )

        total = Decimal(str(row.total_revenue if row else 0)).quantize(
            _CENT, rounding=ROUND_HALF_UP
        )
        return {
            "property_id": property_id,
            "tenant_id": tenant_id,
            "total": format(total, ".2f"),
            "currency": (row.currency if row and row.currency else "USD"),
            "count": int(row.reservation_count if row else 0),
            "month": target_month,
            "year": target_year,
        }
