// Package application exposes pricing to internal transports.
package application

import (
	"context"

	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/domain"
)

// Pricing runs calculations without persistence or settlement.
type Pricing struct{}

func (Pricing) Calculate(request domain.Request) (domain.Result, error) {
	return domain.Calculate(request)
}

// CalculateLegacy checks cancellation around the bounded pure calculation.
func (Pricing) CalculateLegacy(ctx context.Context, input domain.LegacyInput) (domain.LegacyResult, error) {
	if err := ctx.Err(); err != nil {
		return domain.LegacyResult{}, err
	}
	result, err := domain.CalculateLegacy(input)
	if ctx.Err() != nil {
		return domain.LegacyResult{}, ctx.Err()
	}
	return result, err
}
