package http

import (
	"bytes"
	"encoding/json"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/application"
	"github.com/abdumannon-rabbimqulov/Logistika_bot/backend/go/pricing/internal/domain"
)

func TestHTTPContract(t *testing.T) {
	body, err := os.ReadFile("../../domain/testdata/request.json")
	if err != nil {
		t.Fatal(err)
	}
	router := Router(application.Pricing{}, Options{ServiceToken: "test"})
	cases := []struct {
		name, method, path, body string
		status                   int
	}{
		{"health", "GET", "/health", "", 200},
		{"price", "POST", "/internal/v2/calculate", string(body), 200},
		{"invalid values", "POST", "/internal/v2/calculate", "{}", 422},
		{"non-string decimal", "POST", "/internal/v2/calculate", `{"work":{"weight_t":2}}`, 400},
		{"unknown input", "POST", "/internal/v2/calculate", `{"extra": 1}`, 400},
		{"multiple documents", "POST", "/internal/v2/calculate", "{}{}", 400},
		{"oversized payload", "POST", "/internal/v2/calculate", "{}" + strings.Repeat(" ", 64<<10), 400},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			t.Parallel()
			response := httptest.NewRecorder()
			request := httptest.NewRequest(tc.method, tc.path, strings.NewReader(tc.body))
			if tc.path == "/internal/v2/calculate" {
				request.Header.Set("Authorization", "Bearer test")
			}
			router.ServeHTTP(response, request)
			if response.Code != tc.status {
				t.Fatalf("status %d: %s", response.Code, response.Body)
			}
			if tc.name == "price" {
				var result domain.Result
				if err := json.NewDecoder(bytes.NewReader(response.Body.Bytes())).Decode(&result); err != nil {
					t.Fatal(err)
				}
				if result.RecommendedPrice != "232.50" {
					t.Fatalf("unexpected price: %s", result.RecommendedPrice)
				}
			}
		})
	}
}

func TestLegacyHTTPAndReadiness(t *testing.T) {
	const path = "/internal/v1/pricing/calculate"
	const input = `{"distance_km":"2.5","base_price":"10","price_per_km":"2","price_per_ton_km":"1","weight_t":"1.6"}`
	ready := true
	handler := Router(application.Pricing{}, Options{Ready: func() bool { return ready }, ServiceToken: "test"})
	check := func(method, path, body, token string, wantStatus int, wantBody string) {
		t.Helper()
		response := httptest.NewRecorder()
		request := httptest.NewRequest(method, path, strings.NewReader(body))
		if token != "" {
			request.Header.Set("Authorization", "Bearer "+token)
		}
		handler.ServeHTTP(response, request)
		if response.Code != wantStatus || !strings.Contains(response.Body.String(), wantBody) {
			t.Fatalf("got %d %s, want %d containing %s", response.Code, response.Body, wantStatus, wantBody)
		}
	}
	check("GET", "/health/live", "", "", 200, "ok")
	check("GET", "/health/ready", "", "", 200, "ok")
	check("POST", path, input, "", 401, "unauthorized")
	check("POST", path, input, "test", 200, `"price":"28.00"`)
	check("POST", path, `{"distance_km":2.5}`, "test", 400, "invalid_request")
	check("POST", path, "{}{}", "test", 400, "invalid_request")
	check("POST", path, "null", "test", 400, "invalid_request")
	check("POST", path, input+strings.Repeat(" ", 4096), "test", 400, "invalid_request")
	check("POST", path, `{"distance_km":"NaN","base_price":"10","price_per_km":"2"}`, "test", 422, "invalid_pricing_input")
	check("POST", path, `{"distance_km":"5","base_price":"9999999999.99","price_per_km":"1"}`, "test", 422, "price_overflow")
	ready = false
	check("GET", "/health/ready", "", "", 503, "draining")
	check("GET", "/health/live", "", "", 200, "ok")
}

func TestV2Authentication(t *testing.T) {
	const path = "/internal/v2/calculate"
	for _, tc := range []struct { name, token string; expected int }{
		{"missing token", "", 401},
		{"wrong token", "wrong", 401},
		{"valid token", "test", 422},
	} {
		t.Run(tc.name, func(t *testing.T) {
			handler := Router(application.Pricing{}, Options{ServiceToken: "test"})
			req := httptest.NewRequest("POST", path, strings.NewReader("{}"))
			if tc.token != "" { req.Header.Set("Authorization", "Bearer "+tc.token) }
			resp := httptest.NewRecorder()
			handler.ServeHTTP(resp, req)
			if resp.Code != tc.expected { t.Fatalf("got %d, want %d", resp.Code, tc.expected) }
		})
	}
	unconfigured := Router(application.Pricing{}, Options{})
	resp := httptest.NewRecorder()
	unconfigured.ServeHTTP(resp, httptest.NewRequest("POST", path, strings.NewReader("{}")))
	if resp.Code != 401 { t.Fatalf("unconfigured V2 endpoint returned %d, want 401", resp.Code) }
}
