"""Versioned Go Pricing V2 admin configuration.

Drafts and published profiles are configuration only. Order pricing remains Python V1.
Never read live orders or write existing truck_types pricing columns from this module.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict, model_validator
from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from Admin_panel.validation import is_admin
from config.base import Base
from config.config import get_db
from driver.models import TruckType
from users.models import User


class PricingV2Tariff(Base):
    __tablename__ = "pricing_v2_tariffs"
    __table_args__ = (UniqueConstraint("truck_type_id", "version", name="uq_pricing_v2_truck_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    truck_type_id: Mapped[int] = mapped_column(ForeignKey("truck_types.id", ondelete="RESTRICT"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    profile: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# Go domain accepts nonnegative decimal strings (max 10 integer, 12 fractional digits).
# Narrower monetary limit matches SQL Numeric(12,2) in the current Python backend.
NonNegative = Decimal
class Rates(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fuel_uzs_per_liter: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    loaded_liters_per_100_km: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    empty_liters_per_100_km: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    operation_uzs_per_km: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    driving_uzs_per_hour: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    loading_uzs_per_hour: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    unloading_uzs_per_hour: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    waiting_uzs_per_hour: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    handling_uzs_per_ton: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    handling_uzs_per_m3: Decimal = Field(ge=0, le=Decimal("9999999999.99"))


class Bounds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum: Decimal = Field(gt=0, le=1)
    maximum: Decimal = Field(ge=1, le=10)


class Rules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    minimum_price_uzs: Decimal = Field(gt=0, le=Decimal("9999999999.99"))
    target_margin_uzs: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    minimum_net_margin_uzs: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    commission_rate: Decimal = Field(ge=0, lt=1)
    route_bounds: Bounds
    demand_bounds: Bounds

    @model_validator(mode="after")
    def ensure_margin(self):
        if self.target_margin_uzs < self.minimum_net_margin_uzs:
            raise ValueError("Target margin must not be below minimum net margin")
        return self


class EmptyRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    distance_km: Decimal = Field(ge=0, le=Decimal("9999999999.99"))
    duration_min: Decimal = Field(ge=0, le=Decimal("9999999999.99"))

    @model_validator(mode="after")
    def check_leg(self):
        if (self.distance_km == 0) != (self.duration_min == 0):
            raise ValueError("Empty run distance and duration must both be zero or positive")
        return self


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    costs: Rates
    rules: Rules
    configured_empty_run: EmptyRun | None = None


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Draft form values can be previewed without saving.
    profile: DraftInput
    distance_km: Decimal = Field(gt=0, le=Decimal("9999999999.99"))
    duration_min: Decimal = Field(gt=0, le=Decimal("9999999999.99"))
    weight_t: Decimal = Field(gt=0, le=Decimal("9999.99"))
    volume_m3: Decimal | None = Field(default=None, ge=0, le=Decimal("9999.99"))
    loading_min: Decimal = Field(default=0, ge=0)
    unloading_min: Decimal = Field(default=0, ge=0)
    waiting_min: Decimal = Field(default=0, ge=0)
    regional_factor: Decimal = Field(default=1, gt=0)
    demand_signal: Decimal = Field(default=1, gt=0)


router = APIRouter(prefix="/pricing-v2", tags=["Admin Pricing V2"], dependencies=[Depends(is_admin)])


async def _truck(db: AsyncSession, truck_type_id: int) -> TruckType:
    truck = await db.get(TruckType, truck_type_id)
    if truck is None:
        raise HTTPException(status_code=404, detail="Transport turi topilmadi")
    return truck


def _profile_values(data: DraftInput) -> dict:
    # Store decimal strings, not JSON floats; Go uses exact rational arithmetic.
    return data.model_dump(mode="json")


@router.get("/truck-types/{truck_type_id}")
async def versions(truck_type_id: int, db: AsyncSession = Depends(get_db)):
    await _truck(db, truck_type_id)
    rows = (await db.execute(select(PricingV2Tariff).where(PricingV2Tariff.truck_type_id == truck_type_id)
        .order_by(PricingV2Tariff.version.desc()))).scalars().all()
    return [{"id": row.id, "version": row.version, "status": row.status,
             "profile": row.profile, "created_at": row.created_at, "published_at": row.published_at} for row in rows]


@router.put("/truck-types/{truck_type_id}/draft")
async def save_draft(truck_type_id: int, data: DraftInput, db: AsyncSession = Depends(get_db),
                     admin: User = Depends(is_admin)):
    await _truck(db, truck_type_id)
    # Lock truck row so concurrent admins cannot allocate identical next versions.
    await db.execute(select(TruckType).where(TruckType.id == truck_type_id).with_for_update())
    rows = (await db.execute(select(PricingV2Tariff).where(PricingV2Tariff.truck_type_id == truck_type_id)
        .order_by(PricingV2Tariff.version.desc()))).scalars().all()
    latest = rows[0] if rows else None
    if latest and latest.status == "draft":
        latest.profile = _profile_values(data)
    else:
        latest = PricingV2Tariff(truck_type_id=truck_type_id, version=(rows[0].version + 1 if rows else 1),
                                 status="draft", profile=_profile_values(data), created_by=admin.id)
        db.add(latest)
    await db.commit()
    await db.refresh(latest)
    return {"id": latest.id, "version": latest.version, "status": latest.status}


@router.post("/truck-types/{truck_type_id}/preview")
async def preview(truck_type_id: int, data: PreviewInput, db: AsyncSession = Depends(get_db)):
    truck = await _truck(db, truck_type_id)
    if data.weight_t > truck.max_weight or (data.volume_m3 is not None and data.volume_m3 > truck.max_volume):
        raise HTTPException(status_code=422, detail="Yuk og'irligi yoki hajmi transport sig'imidan oshgan")
    # Internal URL and secret are configured on the server. Never expose these to the browser.
    endpoint = os.environ.get("PRICING_GO_URL", "").rstrip("/")
    token = os.environ.get("PRICING_SERVICE_TOKEN", "")
    if not endpoint or not token:
        raise HTTPException(status_code=503, detail="Go Pricing V2 preview hozircha sozlanmagan")
    # V2 quote is simulation only, never used to update orders.
    profile = {
        "truck_type_id": truck_type_id, "tariff_version_id": 1,
        "max_weight_t": str(truck.max_weight), "max_volume_m3": str(truck.max_volume),
        **_profile_values(data.profile),
    }
    body = {
        "profile": profile,
        "route": {"distance_km": str(data.distance_km), "duration_min": str(data.duration_min), "source": "osrm"},
        "work": {"weight_t": str(data.weight_t), "volume_m3": str(data.volume_m3) if data.volume_m3 is not None else None,
                 "loading_min": str(data.loading_min), "unloading_min": str(data.unloading_min),
                 "waiting_min": str(data.waiting_min), "additional_services_uzs": []},
        "regional_factor": str(data.regional_factor), "demand_signal": str(data.demand_signal),
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.post(endpoint + "/internal/v2/calculate", json=body,
                headers={"Authorization": "Bearer " + token})
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail="Go Pricing V2 bilan ulanish mavjud emas") from exc
    if response.status_code != 200:
        # Do not leak Go internal request details, tokens or arbitrary internal errors.
        raise HTTPException(status_code=503 if response.status_code >= 500 else 422,
                            detail="Go Pricing V2 narxni hisoblay olmadi")
    return response.json()


@router.post("/truck-types/{truck_type_id}/publish")
async def publish(truck_type_id: int, db: AsyncSession = Depends(get_db)):
    await _truck(db, truck_type_id)
    await db.execute(select(TruckType).where(TruckType.id == truck_type_id).with_for_update())
    latest = (await db.execute(select(PricingV2Tariff).where(PricingV2Tariff.truck_type_id == truck_type_id)
        .order_by(PricingV2Tariff.version.desc()).limit(1))).scalar_one_or_none()
    if latest is None or latest.status != "draft":
        raise HTTPException(status_code=409, detail="E'lon qilinadigan draft tarif mavjud emas")
    # Publishing only marks a V2 profile ready for future rollout; Python V1 stays authoritative.
    latest.status = "published"
    latest.published_at = datetime.now(timezone.utc)
    await db.commit()
    return {"id": latest.id, "version": latest.version, "status": latest.status, "active_in_orders": False}
