"""V2 tariff validation and isolation; no real database or Go dependency."""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from services.pricing_v2_admin import DraftInput, PreviewInput, _profile_values


def example():
    return {
        "costs": {
            "fuel_uzs_per_liter": "12000",
            "loaded_liters_per_100_km": "20",
            "empty_liters_per_100_km": "15",
            "operation_uzs_per_km": "500",
            "driving_uzs_per_hour": "25000",
            "loading_uzs_per_hour": "10000",
            "unloading_uzs_per_hour": "10000",
            "waiting_uzs_per_hour": "10000",
            "handling_uzs_per_ton": "1000",
            "handling_uzs_per_m3": "0",
        },
        "rules": {
            "minimum_price_uzs": "50000",
            "target_margin_uzs": "40000",
            "minimum_net_margin_uzs": "20000",
            "commission_rate": "0.10",
            "route_bounds": {"minimum": "0.90", "maximum": "1.20"},
            "demand_bounds": {"minimum": "0.90", "maximum": "1.20"},
        },
        "configured_empty_run": None,
    }


def test_profile_json_serializes_decimals_as_strings():
    output = _profile_values(DraftInput.model_validate(example()))
    assert output["costs"]["fuel_uzs_per_liter"] == "12000"
    assert output["rules"]["commission_rate"] == "0.10"
    assert isinstance(output["costs"]["fuel_uzs_per_liter"], str)


@pytest.mark.parametrize("field,value", [
    ("commission_rate", "1"),
    ("minimum_price_uzs", "0"),
    ("minimum_net_margin_uzs", "999999"),
    ("target_margin_uzs", "-1"),
])
def test_invalid_pricing_rules_rejected(field, value):
    payload = example()
    payload["rules"][field] = value
    with pytest.raises(ValidationError):
        DraftInput.model_validate(payload)


def test_invalid_bounds_rejected():
    payload = example()
    payload["rules"]["route_bounds"]["minimum"] = "1.10"
    with pytest.raises(ValidationError):
        DraftInput.model_validate(payload)


def test_unknown_fields_rejected():
    payload = example()
    payload["secret"] = "unexpected"
    with pytest.raises(ValidationError):
        DraftInput.model_validate(payload)


def test_preview_requires_positive_distance_and_weight():
    payload = {
        "profile": example(),
        "distance_km": "0",
        "duration_min": "10",
        "weight_t": "1",
    }
    with pytest.raises(ValidationError):
        PreviewInput.model_validate(payload)
    payload["distance_km"] = "100"
    assert PreviewInput.model_validate(payload).distance_km == Decimal("100")
    payload["weight_t"] = "-1"
    with pytest.raises(ValidationError):
        PreviewInput.model_validate(payload)


def test_zero_or_positive_empty_run_pair():
    payload = example()
    payload["configured_empty_run"] = {"distance_km": "10", "duration_min": "0"}
    with pytest.raises(ValidationError):
        DraftInput.model_validate(payload)
    payload["configured_empty_run"]["duration_min"] = "15"
    assert DraftInput.model_validate(payload).configured_empty_run.duration_min == 15

@pytest.mark.asyncio
async def test_legacy_preview_matches_python_truck_price():
    from services.pricing_v2_admin import LegacyPreviewInput, legacy_preview
    request = LegacyPreviewInput(
        base_price=Decimal("50000"), price_per_km=Decimal("1000"),
        price_per_ton_km=Decimal("100"), min_price=Decimal("0"),
        distance_km=Decimal("112.5"), weight_t=Decimal("5"),
    )
    answer = await legacy_preview(request)
    assert answer == {"price": "222500.00", "billable_distance_km": 115}
