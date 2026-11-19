# Backend arxitekturasi

> Yuk tashish platformasi (Telegram bot + Mini App) backendining tuzilishi.
> Hujjat **joriy kod** asosida yozilgan (2026-11). Eski `SYSTEM_DESIGN.md` va
> `TECH_RECOMMENDATIONS.md` dagi ba'zi gaplar (masalan "migratsiya yo'q") endi
> to'g'ri emas — shubha bo'lsa shu hujjatga va kodga tayaning.

---

## 1. Umumiy ko'rinish

```
                         Internet  :80 / :443
                               │
                           [caddy]  — HTTPS (Let's Encrypt avtomatik)
                               │
                         [frontend] nginx — React SPA (statik dist/)
          ┌────────────┬───────┴───────┬─────────────────────┐
        /api/*      /static/*      /support/*        /osrm/route/v1/*
          │             │               │                     │  (5 r/s, faqat GET)
          ▼             ▼               ▼                     ▼
       [web] FastAPI ◄──┘          [support] FastAPI       [osrm]
          │                             │  (alohida baza)
          │                             │
   ┌──────┼──────────┬──────────────────┼──────────────┐
   ▼      ▼          ▼                  ▼              ▼
 [db]  [redis]  [rabbitmq] ◄───────────────────────────┘
 Postgres          │   ▲
 + PostGIS         │   │ publish
                   ▼   │
     [dispatch-worker] [notification]       [bot] aiogram (polling)
                                                 │
                                          Telegram Bot API
```

| Xizmat | Kod | Vazifasi |
|---|---|---|
| `web` | `config/main.py` (uvicorn) | Asosiy REST API + WebSocket |
| `bot` | `main.py` (aiogram, polling) | Ro'yxatdan o'tish, dispatch tugmalari, Mini App menyu tugmasi |
| `dispatch-worker` | `workers/dispatch_worker.py` | Haydovchi qidirish navbatini bajaradi |
| `notification` | `notification_service` | Support hodisalari → adminlarga Telegram xabar |
| `support` | `support_service/` | Murojaatlar (ticket) mikroservisi, **o'z bazasi** |
| `migrate` | `scripts/docker-entrypoint.sh` | Bir martalik: sxema/alembic, keyin tugaydi |
| `db` | `postgis/postgis:15-3.4` | Asosiy baza + `support_db` |
| `logistika-redis` | `redis:7` | Jonli GPS, rate limit, refresh-token blacklist, qulflar |
| `rabbitmq` | `rabbitmq:3.13` | Dispatch vazifalari va xizmatlararo hodisalar |
| `osrm` | `osrm/osrm-backend` | Self-hosted marshrut/masofa (O'zbekiston xaritasi) |
| `frontend` / `caddy` | `Frontend/`, `Caddyfile` | SPA + reverse proxy + TLS |

`web`, `bot`, `dispatch-worker`, `notification` va `migrate` — **bitta Docker image**
(`logistika_backend`, `Dockerfile`), faqat ishga tushirish buyrug'i farq qiladi.

---

## 2. Texnologiyalar

- **Python 3.11**, **FastAPI** (async), **SQLAlchemy 2.0** (async, `asyncpg`)
- **Alembic** — migratsiyalar (`migrations/versions/`)
- **PostgreSQL 15 + PostGIS** (`geoalchemy2`, `shapely`) — marshrut geometriyasi (`order_route_postgis`)
- **aiogram 3** — Telegram bot
- **aio-pika** — RabbitMQ (to'liq async; sinxron `pika` event loop'ni bloklardi)
- **redis.asyncio** — kesh, jonli joylashuv, rate limit
- **python-jose** — JWT, **bcrypt** — parollar, **phonenumbers** — telefon normalizatsiyasi
- **httpx** — OSRM va Yandex Geocoder chaqiruvlari

---

## 3. Papkalar tuzilishi

```
config/            Ilova yadrosi
  main.py            FastAPI app, lifespan, router'larni ulash, CORS, /health
  config.py          .env o'qish (DATABASE_URL, ADMIN_IDS, REDIS_*, RABBITMQ_URL ...)
  base.py            SQLAlchemy DeclarativeBase
  registry.py        BARCHA modellarni import qiladi (alembic va create_all uchun)

users/             Autentifikatsiya va foydalanuvchilar
  router.py          /auth/* — login, refresh, me, parol, rol tanlash
  auth.py            JWT yaratish/tekshirish, get_current_user
  permissions.py     Rollar bo'yicha ruxsatlar (is_admin_user, STAFF_ROLES ...)
  telegram_auth.py   Telegram WebApp initData imzosini tekshirish
  models.py          User, BalanceTransaction, VerificationCode
  crud.py, schemas.py

driver/            Haydovchilar va transport turlari
  router.py          /drivers/* — profil, truck-types, daromad, WS /ws/location
  models.py          Driver, TruckType

order/             Buyurtmalar
  router.py          /orders/* — yaratish, narx, holat, waypoint, dispatch javoblari
  models.py          Order, OrderWaypoint, OrderRoutePostGIS
  dispatch_models.py DispatchAttempt
  crud.py, schemas.py

Admin_panel/       Admin (moliya va tizim) — /system/*
manager/           Menejer (operativ, moliyasiz) — /manager/*

services/          Biznes-mantiq (router'lardan ajratilgan, qayta ishlatiladi)
workers/           RabbitMQ consumer'lari (fon jarayonlari)
handlers/          aiogram handler'lari (/start, dispatch tugmalari)
keyboards/         Bot klaviaturalari
middlewares/       Global xatolik ushlagich (error_handler.py)
utils/             Validatsiya, telefon normalizatsiyasi, geo, admin alertlari
support_service/   Mustaqil support mikroservisi (o'z Dockerfile, o'z bazasi)
migrations/        Alembic
scripts/           Deploy, OSRM xaritasi, seed, entrypoint
tests/             pytest (DB'siz unit/HTTP testlar)
```

**Qatlamlar qoidasi:** `router` → `services` / `crud` → `models`.
Router'da faqat HTTP (validatsiya, ruxsat, javob), biznes-qoidalar `services/` da.
Bir xil mantiq ham API, ham bot tomonidan kerak bo'lsa (masalan dispatch qabul/rad) —
u `services/` da turadi, ikkalasi ham shuni chaqiradi.

---

## 4. API (router'lar)

Barcha router'lar ikki marta ulanadi: prefikssiz (`/orders`) va `API_PUBLIC_PREFIX`
bilan (`/api/orders`, nginx shu orqali proxy qiladi). Swagger: `/api/docs`.

| Prefiks | Fayl | Asosiy endpointlar | Kim |
|---|---|---|---|
| `/auth` | `users/router.py` | `POST /login` (initData yoki telefon+parol), `POST /refresh`, `GET/PATCH /me`, `PATCH /me/password`, `POST /select-role`, `POST /reset-phone`, `/verify-reset-code`, `/reset-password`, `DELETE /me`, `POST /logout` | hamma |
| `/orders` | `order/router.py` | `POST ""`, `GET ""`, `POST /estimate-price`, `GET /geocode/search\|reverse`, `GET /{id}`, `PATCH /{id}/waypoints/{wid}`, `GET/PATCH /{id}/price`, `POST /{id}/price-bump`, `POST /{id}/dispatch/pause\|resume`, `POST /dispatch/{attempt}/accept\|reject`, `GET /available/list` (`?skip=&limit=`, max 200), `DELETE /{id}`, WS `/{id}/ws/driver-location` | sender, driver |
| `/drivers` | `driver/router.py` | `POST /profile`, `GET/PATCH /me`, `GET /me/earnings`, `GET /me/balance/transactions`, `/truck-types` CRUD (yozish — admin), WS `/ws/location` | driver, admin |
| `/system` | `Admin_panel/router.py` | `/dashboard/stats`, `/users` CRUD, `/users/{id}/balance/adjust\|transactions`, `/orders`, `/drivers`, `/drivers/{id}/block\|unblock`, `/drivers/monitor`, `/drivers/{id}/location`, `/settings/commission\|pricing`, WS `/drivers/locations/stream` | **faqat admin** |
| `/manager` | `manager/router.py` | `/orders`, `/orders/{id}`, `PATCH /orders/{id}/status`, `/orders/{id}/available-trucks`, `POST /orders/{id}/assign-truck` | menejer, admin |
| `/support` | `support_service/router.py` | `/tickets`, `/tickets/{id}`, `/tickets/{id}/messages`, `/tickets/{id}/status` | hamma (alohida xizmat) |
| — | `config/main.py` | `GET /health`, `GET /health/db` | monitoring |

---

## 5. Autentifikatsiya va ruxsatlar

### Kirish usullari (`POST /auth/login`)

1. **Telegram Mini App** — frontend `initData` yuboradi, backend uni `BOT_TOKEN` bilan
   HMAC-imzo orqali tekshiradi (`users/telegram_auth.py`). Foydalanuvchi bazada bo'lmasa
   `GUEST` sifatida yaratiladi, keyin `POST /auth/select-role` bilan sender/driver bo'ladi.
2. **Brauzer (telefon + parol)** — Telegram'siz kirish (asosan admin/menejer paneli).
   Parol profilda o'rnatiladi (`PATCH /auth/me/password`; parol hali bo'lmasa eski parol
   so'ralmaydi). Telefon+IP bo'yicha Redis rate limit bor.

### Tokenlar

- **Access JWT** — `ACCESS_TOKEN_EXPIRE_MINUTES` (standart 60 daqiqa).
- **Refresh JWT** — `REFRESH_TOKEN_EXPIRE_DAYS`, **bir martalik**: ishlatilgani Redis'dagi
  `blacklist_refresh_<token>` ga yoziladi (token rotatsiyasi).
- WebSocket'larda token `?token=` query parametri orqali.

### Rollar (`users/models.py` `UserRole`)

| Rol | Huquqlar |
|---|---|
| `guest` | faqat rol tanlash |
| `sender` | buyurtma yaratish, narx, kuzatish |
| `driver` | profil, takliflarni qabul/rad, waypoint qadamlari, GPS |
| `manager` | buyurtmalarni boshqarish, mashina biriktirish — **moliyasiz** |
| `admin` | hammasi, shu jumladan moliya (`/system`) |
| `dispatcher` | enum'da bor, hozir ishlatilmaydi |

**Admin aniqlash:** `.env` dagi `ADMIN` (Telegram ID'lar). Bunday foydalanuvchi bot
`/start` da ham, Mini App login'da ham avtomatik `admin` roliga o'tkaziladi.
`is_admin_user()` bazadagi rolni **yoki** `ADMIN_IDS` ni tekshiradi.

**Moliya chegarasi** ikki qavatli: (1) barcha moliyaviy endpointlar `/system` ostida va
`is_admin` dependency bilan — u menejerni o'tkazmaydi; (2) menejer javob sxemalarida
narx maydonlari umuman yo'q (`manager/schemas.py`).

---

## 6. Ma'lumotlar modeli

```
users ──1:1── drivers ──N:1── truck_types
  │              │
  │ customer_id  │ driver_id
  ▼              ▼
orders ──1:N── order_waypoints
  │ ──1:1── order_route_postgis   (marshrut LINESTRING, PostGIS)
  │ ──1:N── dispatch_attempts ──N:1── drivers
users ──1:N── balance_transactions
users ──1:N── verification_codes
platform_settings  (bitta qator: komissiya %, sender chegirma chegarasi %)

support_db:  support_tickets ──1:N── support_messages   (alohida baza)
```

| Jadval | Muhim maydonlar |
|---|---|
| `users` | `id` = **Telegram ID** (BigInteger PK), `role`, `phone_number` (login), `password` (bcrypt, ixtiyoriy), `balance`, `is_banned`, `is_active` |
| `drivers` | `user_id`, `truck_type_id`, `truck_number`, `is_available`, `available_from_date`, `last_latitude/longitude`, `verification_status`, `is_blocked`, `rating` |
| `truck_types` | `max_weight`, `max_volume`, o'lchamlar, `base_price`, `price_per_km`, `min_price` |
| `orders` | `customer_id`, `driver_id`, `status`, `price`, `base_price`, `original_price`, `total_distance_km` (OSRM aniq), `billable_distance_km` (5 km ga yaxlitlangan), `pickup_at`, `departure_at`, `dispatch_round`, `price_bump_count`, `dispatch_paused_at`, `unloading_mode` |
| `order_waypoints` | `sequence`, `type` (PICKUP/TRANSIT/DELIVERY), `status`, `address`, `lat/lon` |
| `dispatch_attempts` | `order_id`, `driver_id`, `round_number`, `match_type` (gps/region), `status`, `expires_at`, `bot_message_id` |
| `balance_transactions` | `ORDER_COMMISSION` / `ADMIN_ADJUSTMENT` |

**Holatlar:**

- `OrderStatus`: `SCHEDULED` → `PENDING` → `ACCEPTED` → `IN_PROGRESS` → `COMPLETED`; istalgan bosqichda `CANCELLED`.
- `WaypointStatus`: `PENDING` → `ARRIVED` → `COMPLETED` (yoki `SKIPPED`).
- `DispatchAttemptStatus`: `pending` → `accepted` / `rejected` / `expired` / `cancelled`.

---

## 7. Asosiy biznes oqimlari

### 7.1. Buyurtma yaratish va narx

```
Sender (Mini App)
  ├─ GET  /orders/geocode/search|reverse   → services/yandex_geocoder.py
  ├─ POST /orders/estimate-price           → services/osrm_client.py (masofa, geometriya)
  │                                          → services/pricing.py (5 km yaxlitlash,
  │                                            base_price + km × price_per_km, min_price)
  └─ POST /orders                          → order/crud.py
        ├─ marshrut OSRM'dan, geometriya PostGIS'ga
        ├─ narx FAQAT serverda hisoblanadi (frontend narxi ishonilmaydi)
        └─ services/queue.py → "shu order uchun qidiruv" xabari
```

OSRM ishlamasa narx/yaratish **503** qaytaradi (`OSRMUnavailableError`) — OSRM
majburiy komponent.

Sender narxni oshirishi cheklanmagan; pasaytirishi `platform_settings.sender_max_discount_percent`
(standart 15%) dan oshmaydi.

### 7.2. Dispatch — haydovchi qidirish (`services/dispatch.py`)

```
POST /orders ─► RabbitMQ dispatch.jobs ─► dispatch-worker ─► run_dispatch_job()
                                                │
               ┌────────────────────────────────┘
               ▼
  1. Nomzod tanlash: Tier A — jonli GPS bo'yicha eng yaqin (Redis),
                     Tier B — GPS yo'q bo'lsa region/shahar bo'yicha
  2. DispatchAttempt(pending, 60s) + Telegram taklif (Qabul / Rad)
  3. dispatch.delayed (TTL 60s) ─dead-letter─► dispatch.jobs  (javob taymeri)
  4. Rad / javobsiz → keyingi nomzod (MAX_ROUNDS = 5)
  5. Hech kim olmasa → senderga narx oshirish taklifi (MAX_PRICE_BUMPS = 3)
```

- Bir order uchun bir vaqtda **faqat bitta** `pending` taklif bor. Qabul qilish atomik
  `UPDATE ... WHERE status='pending'` — ikki haydovchi bir orderni ololmaydi.
- Order bo'yicha Redis qulfi (`DISPATCH_LOCK_TTL_SEC = 30`) parallel ishlovchilardan himoya qiladi.
- Rejalashtirilgan buyurtmalar uchun qidiruv yuklashdan `DISPATCH_LEAD_HOURS` (24 soat)
  oldin boshlanadi; ungacha order `SCHEDULED`.
- Taymerlar `asyncio` da emas, RabbitMQ'da (dead-letter TTL) — worker qayta ishga tushsa
  ham yo'qolmaydi.
- Qabul/rad bot tugmasi (`handlers/dispatch.py`) yoki WebApp (`POST /orders/dispatch/...`)
  orqali — ikkalasi ham bitta servisni chaqiradi.

### 7.3. Bajarish — waypoint holat mashinasi (`services/order_flow.py`)

```
Waypoint #1 PICKUP    PENDING → ARRIVED → COMPLETED ─┐ birinchi PICKUP yopilishi
Waypoint #2 TRANSIT   PENDING → ARRIVED → COMPLETED  │   → order IN_PROGRESS
Waypoint #N DELIVERY  PENDING → ARRIVED → COMPLETED ─┘ oxirgisi yopilishi
                                                       → order COMPLETED (+komissiya)
```

- `Order.status` waypoint'lardan **kelib chiqadi**, to'g'ridan-to'g'ri o'zgartirilmaydi.
- Har qadamda **geofence** (`services/geofence.py`): haydovchi nuqtaga GPS bo'yicha
  yaqin bo'lishi shart. Barcha buzilishlar birdaniga qaytariladi (`services/problems.py`).

### 7.4. Moliya (`services/billing.py`)

- `COMPLETED` bo'lganda komissiya (`platform_settings.commission_percent`) haydovchi
  balansidan avtomatik yechiladi → `balance_transactions`.
- Balans manfiy bo'lsa haydovchi avtomatik **bloklanadi** (liniyaga chiqa olmaydi,
  taklif olmaydi). Admin `POST /system/users/{id}/balance/adjust` bilan to'ldiradi.

### 7.5. Jonli joylashuv (`services/live_location.py`)

- Haydovchi: WS `/drivers/ws/location` → Redis `driver_location:{driver_id}`
  (TTL `LIVE_LOC_TTL_SEC` = 120s).
- Bazaga faqat `LIVE_LOC_DB_THROTTLE_SEC` (60s) da bir marta yoziladi (`drivers.last_*`).
- Sender kuzatuvi: WS `/orders/{id}/ws/driver-location`; admin xaritasi:
  WS `/system/drivers/locations/stream`. Redis'da `KEYS` emas, `SCAN` ishlatiladi.

---

## 8. RabbitMQ topologiyasi (`services/queue.py`)

```
logistika.dispatch (direct, durable)          — VAZIFALAR (bitta iste'molchi)
  ├── "dispatch"       → dispatch.jobs        ← dispatch-worker (prefetch = DISPATCH_PREFETCH)
  └── "dispatch.dead"  → dispatch.dead        — urinishlar tugagan xabarlar
dispatch.delayed  (iste'molchisiz; x-message-ttl → dead-letter → dispatch.jobs)

logistika.events (topic, durable)             — HODISALAR (ko'p iste'molchi)
  ├── order.status_changed  ─┬→ support.order_events   ← support xizmati
  ├── order.truck_assigned  ─┘
  ├── support.ticket_created ─┬→ support.notifications ← notification → adminlarga Telegram
  └── support.ticket_replied ─┘
```

Topologiya har bir jarayonda idempotent e'lon qilinadi (`declare_topology`) — qaysi
xizmat birinchi ko'tarilishidan qat'i nazar xabar yo'qolmaydi.

---

## 9. Support mikroservisi (`support_service/`)

- Mustaqil FastAPI ilovasi, o'z `Dockerfile` va **o'z bazasi** (`support_db`).
- Asosiy loyiha kodini ham, bazasini ham **import qilmaydi**. Bog'lovchi faqat:
  umumiy `SECRET_KEY` (JWT tekshirish) va RabbitMQ `logistika.events`.
- Telegram'ga o'zi yozmaydi — "ticket yaratildi" hodisasini e'lon qiladi,
  bildirishnomani `notification` yuboradi.
- Sxema startda `create_all` bilan yaratiladi.

---

## 10. Tashqi integratsiyalar

| Xizmat | Modul | Izoh |
|---|---|---|
| OSRM (self-hosted) | `services/osrm_client.py` | Masofa, vaqt, geometriya. Xarita: `scripts/update-osrm-map.sh` (1–3 oyda bir) |
| Yandex Geocoder | `services/yandex_geocoder.py` | `API_YANDEX_KEY`; manzil qidirish / koordinatadan manzil |
| Telegram Bot API | `handlers/`, `services/notifications.py` | Bot polling; xabarlar API'dan ham yuboriladi |
| Navigatsiya | `services/navigation.py` | Yandex/Google havolalari (ilova ichida marshrut chizilmaydi) |

---

## 11. Ma'lumotlar bazasi va migratsiyalar

- `migrate` konteyneri (`RUN_MIGRATIONS=1`) `scripts/docker-entrypoint.sh` orqali:
  - **toza baza** → `create_all` (modellardan) + `alembic stamp head`
  - **jadval bor, alembic yo'q** → `alembic stamp head`
  - keyin har doim `alembic upgrade head`
- `web`, `bot` va worker'lar `migrate` muvaffaqiyatli tugashini kutadi.
- **Baseline migratsiya yo'q**: birinchi revizya (`8b1137822e41`) `users/orders/drivers`
  mavjud deb hisoblaydi — shuning uchun toza bazada `create_all` yo'li kerak.
- `config/main.py` lifespan'da ham `create_all` chaqiriladi (tarixiy). Yangi ustun/jadval
  qo'shilganda **albatta alembic migratsiyasi** yozing — `create_all` mavjud jadvalni
  o'zgartirmaydi.

```bash
alembic revision --autogenerate -m "tavsif"   # yangi migratsiya
make prod-migrate                              # serverda qo'llash
```

---

## 12. Konfiguratsiya (`.env`)

To'liq namuna va izohlar: `.env.example`. Eng muhimlari:

| Guruh | O'zgaruvchilar |
|---|---|
| Bot / xavfsizlik | `BOT_TOKEN`, `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`, `ADMIN` |
| Baza | `DB_USER`, `DB_PASSWORD`, `DB_NAME`, `DB_HOST`, `DB_URL`, `SUPPORT_DB_NAME` |
| Redis / RabbitMQ | `REDIS_HOST/PORT/DB`, `RABBITMQ_USER/PASSWORD/URL`, `DISPATCH_PREFETCH` |
| Dispatch | `DISPATCH_LEAD_HOURS`, `APP_TIMEZONE` |
| Xarita | `OSRM_BASE_URL`, `API_YANDEX_KEY` |
| GPS | `LIVE_LOC_TTL_SEC`, `LIVE_LOC_DB_THROTTLE_SEC`, `LIVE_LOC_DEFAULT_PERIOD_SEC` |
| Web | `WEBAPP_URL` (https shart), `CORS_ORIGINS`, `API_PUBLIC_PREFIX`, `DOMAIN`, `ACME_EMAIL` |

---

## 13. Xatoliklar, xavfsizlik, kuzatuv

- **Global exception handler** — `middlewares/error_handler.py`: kutilmagan xatolar
  logga yoziladi, mijozga ichki tafsilot (stack, OSRM manzili) berilmaydi.
- **Rate limit** — Redis `INCR` (`_rate_limit_ok`): login, parol tiklash kodi.
- **Validatsiya** — Pydantic sxemalar + `utils/validation.py` (telefon normalizatsiyasi `+998...`).
- **Portlar** — prod'da faqat 80/443 ochiq; db/redis/rabbitmq/osrm/web `127.0.0.1` ga bog'langan.
- **Healthcheck'lar** — `/health`, `/health/db`; compose'da har xizmat uchun.
- **Admin "Server" bo'limi** (`/admin/monitoring`, `GET /system/monitoring`):
  - `services/metrics.py` — sof ASGI middleware har HTTP so'rovni Redis'dagi daqiqalik
    bo'lakka yozadi (`mon:m:<minute>`, `mon:r:<minute>`, 26 soat): soni, 4xx/5xx,
    latency gistogrammasi (p50/p95/p99 shundan), endpoint shabloni bo'yicha. Javob
    boshlanmasdan uzilgan so'rov 499, istisno — 500 sifatida sanaladi. `/health` va
    monitoringning o'zi hisobga olinmaydi. Yozish so'rovni hech qachon yiqitmaydi.
  - `services/monitoring.py` — host resurslari (`/proc`), Postgres (ulanishlar, kesh,
    uzun so'rovlar), Redis, RabbitMQ navbatlari va o'quvchilari (worker tirikligi,
    `dispatch.dead` — yo'qolgan vazifalar), OSRM/Support javob vaqti, qotib qolgan
    buyurtmalar. Har tekshiruv alohida va 3s chegarali — biri yiqilsa qolganlari ko'rinadi.
    Ogohlantirish chegaralari faylning boshida.
- **Monitoring (tashqi)** — Netdata + Dockge, Telegram alertlari (`docs/MONITORING.md`).

---

## 11.1. Tezlik (performance) qoidalari

2026-11 dagi tozalashda topilgan va tuzatilgan sekinlik sabablari — qaytarmang:

| Muammo | Tuzatish |
|---|---|
| `bcrypt` (~250 ms CPU) async handler ichida → butun server to'xtardi | API'da faqat `hash_password_async` / `verify_password_async` (`users/auth.py`, `asyncio.to_thread`) |
| `orders`, `order_waypoints`, `users.phone_number` da indeks yo'q | `f1a6c2e83d47_perf_indexes` migratsiyasi + modellarda `Index(...)` |
| `GET /orders`, `/orders/available/list` sahifalanmagan | `skip` / `limit` (standart 100, max 200) |
| Admin dashboard ~10 ta ketma-ket COUNT | har jadvalga bitta so'rov: `count(*) FILTER (WHERE ...)` |
| DB pool "overflow" ulanishlari yopilib qayta ochilardi; asyncpg har yangi ulanishda PostGIS/enum turlarini qayta o'rganib DB CPU'sini yerdi (yuklama ostida 2 daqiqagacha 1–6 s javob) | web'da `DB_MAX_OVERFLOW=0`, `DB_POOL_SIZE=16` (har worker), pool ishga tushishda isitiladi (`services/db_warmup.py`) |
| Narx hisoblashda web CPU'sining ~60% i marshrut geometriyasiga ketardi (sof Python Douglas-Peucker, WKT qurish, har chaqiruvda yangi HTTP/SSL klient) | `services/osrm_client.py`: umumiy klient, shapely/numpy, ETA/dispatch uchun `with_geometry=False`, narx→buyurtma uchun 10 daqiqalik siqilgan Redis keshi (64 KB dan katta marshrut keshlanmaydi) |
| Bitta uvicorn jarayoni 2 vCPU'dan faqat bittasini ishlatardi | prod'da `--workers 2` (`WEB_WORKERS`), web `mem_limit` 896m |

Yuklama testi (2026-11-19, lokal, prod cheklovlari bilan) — skriptlar repoda yo'q, natijalar:
yangi kod bilan narx hisoblash 3× arzonlashdi (Toshkent–Nukus 38 → 12 ms CPU), 300 sender +
150 haydovchi 1 worker'da p95 5.2 s dan 61 ms ga tushdi.

Qoidalar: ro'yxat endpointlari doim `limit` bilan; WHERE/ORDER BY dagi ustunga indeks;
CPU-og'ir sinxron kod (`bcrypt`, katta JSON/geo hisoblar) → `asyncio.to_thread`;
tashqi HTTP (OSRM, Yandex) → `httpx.AsyncClient` timeout bilan.

Olib tashlangan (hech kim chaqirmagan) endpointlar: `GET /drivers/profile` (`/drivers/me`
dublikati), `GET /drivers/truck-types/{pk}`, `GET /system/drivers/locations` (WS stream bor),
`PATCH /orders/{id}/status` (admin `PATCH /system/orders/{id}` ishlatadi). Bo'sh
`users/tariff_*.py` fayllari ham o'chirildi.

---

## 14. Ishga tushirish va deploy

| Vazifa | Buyruq |
|---|---|
| Lokal to'liq stack | `make up` |
| Testlar | `pytest -q` |
| Prod'ni lokalda sinash | `make prod-local` |
| Serverda deploy | `make deploy` (`scripts/server-deploy.sh`) yoki `main` ga push → GitHub Actions (`.github/workflows/deploy.yml`) |
| OSRM xaritasini yangilash | `./scripts/update-osrm-map.sh` |

### Sinov hisoblari

10 ta sinov hisobi bazada allaqachon yaratilgan va SAQLANADI. Ularni yaratgan
skript (`scripts/seed_test_users.py`) olib tashlangan; kerak bo'lmay qolsa hisoblar
admin panelidan o'chiriladi (yoki bloklanadi).

Parol hammasida `1111`. Kirish: Mini App / brauzerda telefon + parol.

| Rol | Telefonlar |
|---|---|
| Haydovchi 1–5 (tasdiqlangan, liniyada) | `+998900000001` … `+998900000005` |
| Yuboruvchi 1–5 (sender) | `+998900000011` … `+998900000015` |

Batafsil: `docs/DEPLOY.md`, `docs/MICROSERVICES.md`, `docs/DISPATCH_SYSTEM_PLAN.md`.

---

## 15. Yangi funksiya qo'shganda — qisqa qoidalar

1. **Model** → `<modul>/models.py`, keyin `config/registry.py` ga import qo'shing.
2. **Migratsiya** → `alembic revision --autogenerate`, natijani qo'lda tekshiring.
3. **Biznes-qoida** → `services/` da; router faqat chaqiradi.
4. **Ruxsat** → `users/permissions.py` dagi dependency'lar; moliya — faqat `/system` + `is_admin`.
5. **Og'ir yoki kechiktirilgan ish** → HTTP so'rov ichida emas, RabbitMQ navbati orqali worker'da.
6. **Narx/masofa** → faqat serverda hisoblanadi, frontenddan kelgan qiymatga ishonilmaydi.
7. **Boshqa xizmatga xabar** → `logistika.events` ga hodisa e'lon qiling, uning kodini import qilmang.
