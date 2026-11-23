package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/application"
	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/infrastructure"
	pricinghttp "github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/transport/http"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "healthcheck" {
		client := &http.Client{Timeout: 2 * time.Second}
		response, err := client.Get("http://127.0.0.1:8080/health/ready")
		if err != nil {
			log.Fatal(err)
		}
		response.Body.Close()
		if response.StatusCode != http.StatusOK {
			log.Fatalf("readiness returned %d", response.StatusCode)
		}
		return
	}
	if os.Getenv("PRICING_SERVICE_TOKEN") == "" {
		log.Fatal("PRICING_SERVICE_TOKEN must be configured before starting pricing server")
	}
	var ready atomic.Bool
	ready.Store(true)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	server := &http.Server{
		Addr: infrastructure.ListenAddress(), Handler: pricinghttp.Router(application.Pricing{}, pricinghttp.Options{
			Ready: ready.Load, ServiceToken: os.Getenv("PRICING_SERVICE_TOKEN"),
		}),
		ReadHeaderTimeout: 3 * time.Second, ReadTimeout: 5 * time.Second,
		WriteTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second,
	}
	done := make(chan error, 1)
	go func() { done <- server.ListenAndServe() }()
	select {
	case err := <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			log.Fatal(err)
		}
	case <-ctx.Done():
		ready.Store(false)
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdown); err != nil {
			log.Fatal(err)
		}
	}
}
