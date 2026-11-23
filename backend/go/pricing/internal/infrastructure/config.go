package infrastructure

import "os"

func ListenAddress() string {
	if address := os.Getenv("PRICING_LISTEN_ADDRESS"); address != "" {
		return address
	}
	return "127.0.0.1:8080"
}
