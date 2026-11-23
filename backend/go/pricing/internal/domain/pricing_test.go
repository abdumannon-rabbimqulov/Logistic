package domain

import (
	"encoding/json"
	"os"
	"testing"
)

func fixture(t *testing.T) Request {
	t.Helper()
	body, err := os.ReadFile("testdata/request.json")
	if err != nil {
		t.Fatal(err)
	}
	var request Request
	if err := json.Unmarshal(body, &request); err != nil {
		t.Fatal(err)
	}
	return request
}

func ptr(value string) *string { return &value }

func calculate(t *testing.T, request Request) Result {
	t.Helper()
	result, err := Calculate(request)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func TestCalculationAndCosts(t *testing.T) {
	input := fixture(t)
	input.RegionalFactor, input.DemandSignal = ptr("1.2"), ptr("1.1")
	input.ObservedEmptyRun = &EmptyRun{DistanceKM: "4", DurationMin: "8"}
	result := calculate(t, input)
	want := Costs{
		Fuel: "25", Operation: "12.5", DriverTime: "30", Loading: "33",
		Unloading: "15", Waiting: "10", EmptyRun: "16", AdditionalServices: "7", Total: "148.5",
	}
	if result.Costs != want || result.RecommendedPrice != "328.02" ||
		result.ExpectedCommission != "32.80" || result.ExpectedNetMargin != "146.72" ||
		result.EmptyRunSource != "observed" || result.TruckTypeID != 7 || result.TariffVersionID != 12 {
		t.Fatalf("unexpected calculation: %+v", result)
	}
}

func TestFloorsAndMarketBounds(t *testing.T) {
	input := fixture(t)
	input.RegionalFactor, input.DemandSignal = ptr("0.8"), ptr("0.1")
	input.Route.DurationMin = "30.001"
	result := calculate(t, input)
	if result.DemandFactor != "0.9" || result.MarginFloor != "175.02" ||
		result.RecommendedPrice != "175.02" || result.ExpectedNetMargin != "25.019" {
		t.Fatalf("margin floor: %+v", result)
	}
	input.Profile.Rules.MinimumPrice = "200.001"
	if result := calculate(t, input); result.RecommendedPrice != "200.01" {
		t.Fatalf("tariff floor: %+v", result)
	}
	input.DemandSignal = ptr("9")
	if result := calculate(t, input); result.DemandFactor != "1.1" {
		t.Fatalf("upper demand bound: %+v", result)
	}
}

func TestEmptyRunAndCargo(t *testing.T) {
	input := fixture(t)
	result := calculate(t, input)
	if result.DemandFactor != "1" || result.EmptyRunSource != "disabled" {
		t.Fatalf("neutral result: %+v", result)
	}
	input.Profile.ConfiguredEmptyRun = &EmptyRun{DistanceKM: "4", DurationMin: "8"}
	if result := calculate(t, input); result.EmptyRunSource != "configured" || result.Costs.EmptyRun != "16" {
		t.Fatalf("fallback: %+v", result)
	}
	input.ObservedEmptyRun = &EmptyRun{DistanceKM: "0", DurationMin: "0"}
	input.Work.WeightT, input.Work.VolumeM3 = "10", ptr("24")
	if result := calculate(t, input); result.EmptyRunSource != "observed" || result.Costs.EmptyRun != "0" || result.Costs.Loading != "112" {
		t.Fatalf("observed empty run or handling: %+v", result)
	}
	input.Profile.Costs.HandlingPerM3, input.Work.VolumeM3 = "0", nil
	if result := calculate(t, input); result.Costs.Loading != "40" {
		t.Fatalf("unpriced optional volume: %+v", result)
	}
}

func TestRejectsInvalidInputs(t *testing.T) {
	cases := []struct {
		name string
		edit func(*Request)
	}{
		{"NaN", func(r *Request) { r.Work.WeightT = "NaN" }},
		{"infinity", func(r *Request) { r.Route.DistanceKM = "Infinity" }},
		{"negative", func(r *Request) { r.Work.WaitingMin = "-1" }},
		{"zero weight", func(r *Request) { r.Work.WeightT = "0" }},
		{"overweight", func(r *Request) { r.Work.WeightT = "10.01" }},
		{"precision", func(r *Request) { r.Work.WeightT = "0.001" }},
		{"overvolume", func(r *Request) { r.Work.VolumeM3 = ptr("24.01") }},
		{"missing volume", func(r *Request) { r.Work.VolumeM3 = nil }},
		{"estimated route", func(r *Request) { r.Route.Source = "estimated" }},
		{"missing duration", func(r *Request) { r.Route.DurationMin = "0" }},
		{"regional outlier", func(r *Request) { r.RegionalFactor = ptr("1.3") }},
		{"invalid bounds", func(r *Request) { r.Profile.Rules.DemandBounds.Minimum = "1.1" }},
		{"commission at 100%", func(r *Request) { r.Profile.Rules.CommissionRate = "1" }},
		{"money overflow", func(r *Request) { r.Profile.Costs.OperationPerKM = "9999999999.99" }},
		{"incomplete empty run", func(r *Request) { r.ObservedEmptyRun = &EmptyRun{DistanceKM: "4", DurationMin: "0"} }},
		{"negative service", func(r *Request) { r.Work.AdditionalServices = []string{"-1"} }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			input := fixture(t)
			tc.edit(&input)
			if _, err := Calculate(input); err == nil {
				t.Fatal("invalid input accepted")
			}
		})
	}
}
