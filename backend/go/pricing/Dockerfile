FROM golang:1.24-alpine AS builder
WORKDIR /src
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /pricing ./cmd/server

FROM scratch
COPY --from=builder /pricing /pricing
USER 10001:10001
ENV PRICING_LISTEN_ADDRESS=:8080
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD ["/pricing", "healthcheck"]
ENTRYPOINT ["/pricing"]
