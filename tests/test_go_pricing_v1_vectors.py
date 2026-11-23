"""Verify the shared Go contract against the existing Python V1 implementation."""

import json
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path

import pytest

from driver.models import TruckType
from services.pricing import round_distance_km

_VECTORS = (
    Path(__file__).resolve().parents[1]
    / "contracts/testdata/pricing-v1-vectors.json"
)


@pytest.mark.parametrize("vector", json.loads(_VECTORS.read_text()), ids=lambda case: case["name"])
def test_legacy_go_vector_matches_python(vector):
    data = {
        key: Decimal(value) if value is not None else None
        for key, value in vector["input"].items()
    }
    distance = data.pop("distance_km")
    weight = data.pop("weight_t", None)
    truck = TruckType(**data)
    with localcontext(prec=28, rounding=ROUND_HALF_EVEN):
        assert round_distance_km(distance) == vector["expected"]["billable_distance_km"]
        assert str(truck.calculate_price(distance, weight)) == vector["expected"]["price"]
