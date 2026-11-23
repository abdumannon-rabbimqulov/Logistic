package domain

import (
	"errors"
	"math/big"
	"strings"
)

// LegacyInput is the tariff and cargo data already resolved by the caller.
type LegacyInput struct {
	DistanceKM    string  `json:"distance_km"`
	BasePrice     string  `json:"base_price"`
	PricePerKM    string  `json:"price_per_km"`
	PricePerTonKM *string `json:"price_per_ton_km"`
	WeightT       *string `json:"weight_t"`
	MinPrice      *string `json:"min_price"`
}

type LegacyResult struct {
	BillableDistanceKM int64  `json:"billable_distance_km"`
	Price              string `json:"price"`
}

var ErrPriceOverflow = errors.New("price exceeds the order money range")

// CalculateLegacy matches TruckType.calculate_price with the default Python
// Decimal context. Distance uses HALF_UP and the final price uses HALF_EVEN.
func CalculateLegacy(input LegacyInput) (LegacyResult, error) {
	var v validation
	distance := v.number("distance_km", input.DistanceKM, maxMoney, false)
	base := legacyTariff(&v, "base_price", input.BasePrice)
	perKM := legacyTariff(&v, "price_per_km", input.PricePerKM)
	optional := func(name string, raw *string, limit *big.Rat) *big.Rat {
		if raw == nil {
			return zero
		}
		return v.number(name, *raw, limit, false)
	}
	perTonKM, minimum := zero, zero
	if input.PricePerTonKM != nil {
		perTonKM = legacyTariff(&v, "price_per_ton_km", *input.PricePerTonKM)
	}
	if input.MinPrice != nil {
		minimum = legacyTariff(&v, "min_price", *input.MinPrice)
	}
	weight := optional("weight_t", input.WeightT, maxCargo)
	if v.err != nil {
		return LegacyResult{}, v.err
	}

	five := big.NewRat(5, 1)
	steps, _ := new(big.Rat).SetString(divide(distance, five).FloatString(0))
	billableKM := product(steps, five)
	price := most(sum(base, product(billableKM, perKM), product(billableKM, weight, perTonKM)), minimum)

	// The inputs are non-negative. At exactly half a cent, round to an even cent.
	cents := product(price, hundred)
	whole, remainder := new(big.Int), new(big.Int)
	whole.QuoRem(cents.Num(), cents.Denom(), remainder)
	half := remainder.Lsh(remainder, 1).Cmp(cents.Denom())
	if half > 0 || (half == 0 && whole.Bit(0) == 1) {
		whole.Add(whole, big.NewInt(1))
	}
	rounded := new(big.Rat).SetFrac(whole, hundred.Num())
	if rounded.Cmp(maxMoney) > 0 {
		return LegacyResult{}, ErrPriceOverflow
	}
	return LegacyResult{BillableDistanceKM: billableKM.Num().Int64(), Price: rounded.FloatString(2)}, nil
}

// Stored V1 tariffs use Numeric(12,2).
func legacyTariff(v *validation, name, value string) *big.Rat {
	number := v.number(name, value, maxMoney, false)
	if _, fraction, found := strings.Cut(value, "."); found {
		v.check(len(strings.TrimRight(fraction, "0")) <= 2, name+" must have at most two decimal places")
	}
	return number
}
