package domain

import (
	"fmt"
	"math/big"
	"regexp"
	"strings"
)

var (
	decimalPattern = regexp.MustCompile(`^[0-9]{1,10}(\.[0-9]{1,12})?$`)
	zero           = big.NewRat(0, 1)
	one            = big.NewRat(1, 1)
	hour           = big.NewRat(60, 1)
	hundred        = big.NewRat(100, 1)
	maxMoney       = big.NewRat(999999999999, 100)
	maxCargo       = big.NewRat(999999, 100)
)

type validation struct{ err error }

func (v *validation) check(ok bool, message string) {
	if !ok && v.err == nil {
		v.err = fmt.Errorf("%s", message)
	}
}

func (v *validation) number(name, raw string, limit *big.Rat, positive bool) *big.Rat {
	if !decimalPattern.MatchString(raw) {
		v.check(false, name+" must be a non-negative decimal string")
		return zero
	}
	n, _ := new(big.Rat).SetString(raw)
	v.check(n.Cmp(limit) <= 0 && (!positive || n.Sign() > 0), name+" is out of range")
	return n
}

func (v *validation) cargo(name, raw string, limit *big.Rat) *big.Rat {
	if _, fraction, found := strings.Cut(raw, "."); found {
		v.check(len(strings.TrimRight(fraction, "0")) <= 2, name+" must have at most 2 decimal places")
	}
	return v.number(name, raw, limit, true)
}

func (v *validation) bounds(name string, bounds Bounds) (low, high *big.Rat) {
	low = v.number(name+".minimum", bounds.Minimum, maxMoney, true)
	high = v.number(name+".maximum", bounds.Maximum, maxMoney, true)
	v.check(low.Cmp(one) <= 0 && high.Cmp(one) >= 0, name+" must contain neutral factor 1")
	return low, high
}

func product(values ...*big.Rat) *big.Rat {
	result := new(big.Rat).Set(one)
	for _, value := range values {
		result.Mul(result, value)
	}
	return result
}

func sum(values ...*big.Rat) *big.Rat {
	result := new(big.Rat)
	for _, value := range values {
		result.Add(result, value)
	}
	return result
}

func divide(n, d *big.Rat) *big.Rat { return new(big.Rat).Quo(n, d) }

func ceilingMoney(value *big.Rat) *big.Rat {
	cents := product(value, hundred)
	whole, rest := new(big.Int), new(big.Int)
	whole.QuoRem(cents.Num(), cents.Denom(), rest)
	if rest.Sign() > 0 {
		whole.Add(whole, big.NewInt(1))
	}
	return new(big.Rat).SetFrac(whole, hundred.Num())
}

func halfUpMoney(value *big.Rat) *big.Rat {
	rounded, _ := new(big.Rat).SetString(value.FloatString(2))
	return rounded
}

func most(a, b *big.Rat) *big.Rat {
	if a.Cmp(b) < 0 {
		return b
	}
	return a
}

func least(a, b *big.Rat) *big.Rat {
	if a.Cmp(b) > 0 {
		return b
	}
	return a
}

func decimal(value *big.Rat) string {
	return strings.TrimRight(strings.TrimRight(value.FloatString(18), "0"), ".")
}

// Calculate uses exact rational arithmetic up to monetary rounding. Each travel
// leg, on-site activity and per-unit handling charge must represent disjoint costs.
func Calculate(input Request) (Result, error) {
	var v validation
	profile, route, work := input.Profile, input.Route, input.Work
	v.check(profile.TruckTypeID > 0 && profile.TariffVersionID > 0, "truck type and tariff version must be positive")
	v.check(route.Source == "osrm" || route.Source == "osrm_cache", "pricing requires an OSRM route")
	distance := v.number("route.distance_km", route.DistanceKM, maxMoney, false)
	duration := v.number("route.duration_min", route.DurationMin, maxMoney, false)
	v.check(distance.Sign() == 0 || duration.Sign() > 0, "positive route distance requires positive duration")
	weight := v.cargo("weight_t", work.WeightT, v.cargo("max_weight_t", profile.MaxWeightT, maxCargo))
	volume := zero
	maxVolume := v.cargo("max_volume_m3", profile.MaxVolumeM3, maxCargo)
	if work.VolumeM3 != nil {
		volume = v.cargo("volume_m3", *work.VolumeM3, maxVolume)
	}

	rates := profile.Costs
	fuelRate := v.number("fuel rate", rates.FuelPerLiter, maxMoney, false)
	loadedRate := v.number("loaded consumption", rates.LoadedLiters, maxMoney, false)
	emptyRate := v.number("empty consumption", rates.EmptyLiters, maxMoney, false)
	operationRate := v.number("operation rate", rates.OperationPerKM, maxMoney, false)
	drivingRate := v.number("driving rate", rates.DrivingPerHour, maxMoney, false)
	perTon := v.number("ton handling rate", rates.HandlingPerTon, maxMoney, false)
	perVolume := v.number("volume handling rate", rates.HandlingPerM3, maxMoney, false)
	v.check(work.VolumeM3 != nil || perVolume.Sign() == 0, "volume is required when volume is priced")

	fuel := divide(product(distance, loadedRate, fuelRate), hundred)
	operation := product(distance, operationRate)
	driving := divide(product(duration, drivingRate), hour)
	activity := func(name, minutes, rate string) *big.Rat {
		return divide(product(v.number(name+" minutes", minutes, maxMoney, false),
			v.number(name+" rate", rate, maxMoney, false)), hour)
	}
	loading := sum(activity("loading", work.LoadingMin, rates.LoadingPerHour), product(weight, perTon), product(volume, perVolume))
	unloading := activity("unloading", work.UnloadingMin, rates.UnloadingPerHour)
	waiting := activity("waiting", work.WaitingMin, rates.WaitingPerHour)
	additional := new(big.Rat)
	for _, raw := range work.AdditionalServices {
		additional.Add(additional, v.number("additional service", raw, maxMoney, false))
	}

	emptyCost := func(leg *EmptyRun) *big.Rat {
		if leg == nil {
			return zero
		}
		km := v.number("empty-run distance", leg.DistanceKM, maxMoney, false)
		minutes := v.number("empty-run duration", leg.DurationMin, maxMoney, false)
		v.check(km.Sign() == minutes.Sign(), "empty-run distance and duration must both be positive or both zero")
		return sum(divide(product(km, emptyRate, fuelRate), hundred),
			product(km, operationRate), divide(product(minutes, drivingRate), hour))
	}
	empty, emptySource := emptyCost(profile.ConfiguredEmptyRun), "disabled"
	if profile.ConfiguredEmptyRun != nil {
		emptySource = "configured"
	}
	if input.ObservedEmptyRun != nil {
		empty, emptySource = emptyCost(input.ObservedEmptyRun), "observed"
	}

	rules := profile.Rules
	minimum := v.number("minimum price", rules.MinimumPrice, maxMoney, true)
	target := v.number("target margin", rules.TargetMargin, maxMoney, false)
	minimumNet := v.number("minimum net margin", rules.MinimumNetMargin, maxMoney, false)
	rate := v.number("commission rate", rules.CommissionRate, one, false)
	v.check(rate.Cmp(one) < 0, "commission rate must be less than 1")
	v.check(target.Cmp(minimumNet) >= 0, "target margin must cover minimum net margin")

	regional, demand := one, one
	regionalLow, regionalHigh := v.bounds("route bounds", rules.RouteBounds)
	demandLow, demandHigh := v.bounds("demand bounds", rules.DemandBounds)
	if input.RegionalFactor != nil {
		regional = v.number("regional factor", *input.RegionalFactor, maxMoney, true)
	}
	v.check(regional.Cmp(regionalLow) >= 0 && regional.Cmp(regionalHigh) <= 0, "regional factor is out of bounds")
	if input.DemandSignal != nil {
		signal := v.number("demand signal", *input.DemandSignal, maxMoney, true)
		demand = least(demandHigh, most(demandLow, signal))
	}
	if v.err != nil {
		return Result{}, v.err
	}

	cost := sum(fuel, operation, driving, loading, unloading, waiting, empty, additional)
	candidate := product(sum(cost, target), regional, demand)
	net := ceilingMoney(sum(cost, minimumNet))
	floor := ceilingMoney(divide(net, new(big.Rat).Sub(one, rate)))
	price := most(halfUpMoney(candidate), most(ceilingMoney(minimum), floor))
	if price.Cmp(maxMoney) > 0 {
		return Result{}, fmt.Errorf("recommended price exceeds the order money range")
	}
	commission := halfUpMoney(product(price, rate))
	margin := new(big.Rat).Sub(price, sum(commission, cost))
	return Result{
		TruckTypeID: profile.TruckTypeID, TariffVersionID: profile.TariffVersionID,
		Costs: Costs{
			Fuel: decimal(fuel), Operation: decimal(operation), DriverTime: decimal(driving),
			Loading: decimal(loading), Unloading: decimal(unloading), Waiting: decimal(waiting),
			EmptyRun: decimal(empty), AdditionalServices: decimal(additional), Total: decimal(cost),
		},
		RouteFactor: decimal(regional), DemandFactor: decimal(demand), EmptyRunSource: emptySource,
		PriceBeforeGuardrails: decimal(candidate), MinimumPrice: decimal(minimum),
		MarginFloor: floor.FloatString(2), RecommendedPrice: price.FloatString(2),
		ExpectedCommission: commission.FloatString(2), ExpectedNetMargin: decimal(margin),
	}, nil
}
