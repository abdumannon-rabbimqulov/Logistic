# Go Pricing Engine

Bu mustaqil servis Python V1 formulasi bilan mos narx hisoblaydi. FastAPI amaldagi narx hisobini bajarishda davom etadi. Go server JSON’dagi o‘nlik satrlarni math/big.Rat orqali aniq hisoblaydi. Masofa 5 km qadamiga ROUND_HALF_UP, yakuniy narx esa Python V1 Decimal kontekstiga mos ROUND_HALF_EVEN bilan yaxlitlanadi. Natija PostgreSQL Numeric(12,2) chegarasidan oshsa 422 qaytadi.

Kataloglar oqimi — cmd/server → transport → application → domain. Infrastructure server configini o‘qiydi.

## Lokal ishga tushirish

Repo ildizidan:

```sh
docker compose -f backend/go/pricing/compose.yaml up --build -d --wait
curl -fsS http://127.0.0.1:8080/health/ready
curl -fsS http://127.0.0.1:8080/internal/v1/pricing/calculate \
  -H 'Content-Type: application/json' \
  -d '{"distance_km":"112.5","base_price":"10","price_per_km":"2"}'
docker compose -f backend/go/pricing/compose.yaml down
```

Docker local profili portni faqat loopback’ka bog‘laydi. Root Compose’dagi pricing-v2 profili host portini publish qilmaydi. PRICING_SERVICE_TOKEN berilsa V1 endpoint Authorization: Bearer <token> talab qiladi. Dockerfile liveness va readiness endpointlaridan readiness’ni statik binary probe orqali tekshiradi. SIGTERM kelganda readiness o‘chadi va in-flight requests uchun 5 soniyalik shutdown budjeti ishlaydi.

Docker ishlatilmagan holda backend/go/pricing katalogida go run ./cmd/server. Binary default manzili 127.0.0.1:8080.

## TASK 03 uchun

[Contract](../../../contracts/openapi/pricing-v1.yaml) va [umumiy vektorlar](../../../contracts/testdata/pricing-v1-vectors.json) FastAPI adapter uchun tayyor. Keyingi bosqichda trusted caller credential, umumiy request budget, bounded shadow ish va narx tafovuti metrikalari ulanadi. Mijoz javobi uchun avval Python V1 authoritative qoladi.
