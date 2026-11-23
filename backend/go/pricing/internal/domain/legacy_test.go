package domain

import (
	"encoding/json"
	"errors"
	"os"
	"testing"
)

func TestLegacySharedVectors(t *testing.T) {
	body, err := os.ReadFile("../../../../../contracts/testdata/pricing-v1-vectors.json")
	if err != nil {
		t.Fatal(err)
	}
	var vectors []struct {
		Name     string
		Input    LegacyInput
		Expected LegacyResult
	}
	if err := json.Unmarshal(body, &vectors); err != nil {
		t.Fatal(err)
	}
	if len(vectors) == 0 {
		t.Fatal("missing vectors")
	}
	for _, vector := range vectors {
		t.Run(vector.Name, func(t *testing.T) {
			got, err := CalculateLegacy(vector.Input)
			if err != nil || got != vector.Expected {
				t.Fatalf("got %+v, %v; want %+v", got, err, vector.Expected)
			}
		})
	}
}

func TestLegacyRejectsInvalidDecimalsAndOverflow(t *testing.T) {
	for _, bad := range []string{"NaN", "Infinity", "-Infinity", "-1", "10000000000", "0.0000000000001"} {
		t.Run(bad, func(t *testing.T) {
			if _, err := CalculateLegacy(LegacyInput{DistanceKM: bad, BasePrice: "0", PricePerKM: "0"}); err == nil {
				t.Fatal("expected validation error")
			}
		})
	}
	_, err := CalculateLegacy(LegacyInput{DistanceKM: "5", BasePrice: "9999999999.99", PricePerKM: "1"})
	if !errors.Is(err, ErrPriceOverflow) {
		t.Fatalf("expected overflow error, got %v", err)
	}
}
