package application

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/domain"
)

func TestLegacyHonorsCancellationAndDeadline(t *testing.T) {
	canceled, cancel := context.WithCancel(context.Background())
	cancel()
	expired, stop := context.WithDeadline(context.Background(), time.Now().Add(-time.Second))
	defer stop()
	for _, ctx := range []context.Context{canceled, expired} {
		_, err := (Pricing{}).CalculateLegacy(ctx, domain.LegacyInput{})
		if !errors.Is(err, ctx.Err()) {
			t.Fatalf("expected %v, got %v", ctx.Err(), err)
		}
	}
}
