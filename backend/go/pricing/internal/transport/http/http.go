package http

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/application"
	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/domain"
)

type Options struct {
	Ready        func() bool
	ServiceToken string
}

func Router(pricing application.Pricing, options Options) http.Handler {
	mux := http.NewServeMux()
	live := func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	}
	mux.HandleFunc("GET /health", live)
	mux.HandleFunc("GET /health/live", live)
	mux.HandleFunc("GET /health/ready", func(w http.ResponseWriter, r *http.Request) {
		if options.Ready != nil && !options.Ready() {
			writeJSON(w, http.StatusServiceUnavailable, map[string]string{"status": "draining"})
			return
		}
		live(w, r)
	})
	mux.HandleFunc("POST /internal/v1/pricing/calculate", func(w http.ResponseWriter, r *http.Request) {
		if options.ServiceToken != "" && subtle.ConstantTimeCompare(
			[]byte(r.Header.Get("Authorization")), []byte("Bearer "+options.ServiceToken),
		) != 1 {
			writeError(w, http.StatusUnauthorized, "unauthorized", "service credential required")
			return
		}
		ctx, cancel := context.WithTimeout(r.Context(), time.Second)
		defer cancel()
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10))
		decoder.DisallowUnknownFields()
		var input *domain.LegacyInput
		if decoder.Decode(&input) != nil || input == nil || decoder.Decode(new(any)) != io.EOF {
			writeError(w, http.StatusBadRequest, "invalid_request", "expected one pricing JSON object")
			return
		}
		result, err := pricing.CalculateLegacy(ctx, *input)
		switch {
		case errors.Is(err, context.DeadlineExceeded), errors.Is(err, context.Canceled):
			writeError(w, http.StatusGatewayTimeout, "calculation_timeout", "calculation deadline exceeded")
		case errors.Is(err, domain.ErrPriceOverflow):
			writeError(w, http.StatusUnprocessableEntity, "price_overflow", err.Error())
		case err != nil:
			writeError(w, http.StatusUnprocessableEntity, "invalid_pricing_input", err.Error())
		default:
			writeJSON(w, http.StatusOK, result)
		}
	})
	mux.HandleFunc("POST /internal/v2/calculate", func(w http.ResponseWriter, r *http.Request) {
		// V2 must never bypass the same internal service credential used by V1.
		if options.ServiceToken == "" || subtle.ConstantTimeCompare(
			[]byte(r.Header.Get("Authorization")), []byte("Bearer "+options.ServiceToken),
		) != 1 {
			writeError(w, http.StatusUnauthorized, "unauthorized", "service credential required")
			return
		}
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10))
		decoder.DisallowUnknownFields()
		var input domain.Request
		if err := decoder.Decode(&input); err != nil || decoder.Decode(new(any)) != io.EOF {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid pricing request"})
			return
		}
		result, err := pricing.Calculate(input)
		if err != nil {
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, result)
	})
	return mux
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]string{"code": code, "message": message})
}
