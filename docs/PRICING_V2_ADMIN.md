# Admin Pricing V2 — konfiguratsiya va ishga tushirish

## Qayerda?

Admin → Transport turlari → **V2 tarif**.

Oddiy "Tahrirlash" shakli V1 uchun. V2 shaklida real xarajat, marja, komissiya va cheklangan koeffitsiyentlar mavjud. O'zgartirishlar buyurtma narxiga ta'sir qilmaydi: **Python V1 authoritative** bo'lib qoladi.

## Kod oqimi

1. React `Frontend/src/admin/components/TruckTypeV2Modal.tsx` → `Frontend/src/api/pricingV2.ts`.
2. FastAPI `/api/system/pricing-v2/...` → `services/pricing_v2_admin.py`.
3. Admin token `Admin_panel.validation.is_admin` orqali tekshiriladi. Menejer o‘ta olmaydi.
4. Draft `pricing_v2_tariffs` jadvaliga JSON sifatida **decimal string** bilan saqlanadi.
5. Preview FastAPI → Go `/internal/v2/calculate`, server konfiguratsiyasidagi Bearer token bilan.
6. Go `math/big.Rat` orqali narxni hisoblaydi; frontend `recommended_price`, xarajat, komissiya va sof marjani ko‘rsatadi.
7. Publish faqat versiyani "published" qiladi. V2 real buyurtmaga ulanmaydi.

## Migratsiya

`migrations/versions/c9e8a1b47f62_pricing_v2_tariffs.py` yangi jadval yaratadi.
Production deploy'dagi `migrate` servisi Alembic migrationlarni yuritadi.
Oldingi V1 `truck_types` tariflarini o‘zgartirmaydi.

## Go preview'ni yoqish (opt-in)

**Bu amallar faqat server administratori tomonidan bajariladi.** Default productionda Go profili o‘chiq.

Serverdagi `.env` ga kamida 32 baytlik tasodifiy maxfiy tokenni o'zingiz xavfsiz yarating va qo'shing. Tokenni GitHub, frontend env, chat yoki logga yozmang.

```env
PRICING_SERVICE_TOKEN=<serverda xavfsiz yaratilgan maxfiy qiymat>
PRICING_GO_URL=http://pricing-go:8080
COMPOSE_PROFILES=pricing-v2
```

`COMPOSE_PROFILES` mavjud deploy stack’ning barcha konteynerlarini qayta ko‘tarishi mumkin; server administratoriga oldin `docker compose config` va resurs limitlarini tekshirtiring. `pricing-go` ommaviy portga ega emas; GHCR image GitHub deploy pipeline’da build qilinadi. Asosiy FastAPI `web` container `.env` orqali tokenni oladi. O‘zgartirilgan env qiymatlari uchun web qayta yaratilishi kerak.

Go servisi ishga tushmasa preview 503 beradi; admin V2 draftni saqlashi mumkin, Python V1 ishlashda davom etadi.

## API

- `GET /api/system/pricing-v2/truck-types/{id}` — barcha V2 tarif versiyalari
- `PUT /api/system/pricing-v2/truck-types/{id}/draft` — draft saqlash; publish qilingan versiyani o‘zgartirmaydi
- `POST /api/system/pricing-v2/truck-types/{id}/preview` — Go'da narx simulyatsiyasi
- `POST /api/system/pricing-v2/truck-types/{id}/publish` — versiyani e'lon qilish, buyurtmaga ta'sir **yo'q**
- `POST /api/system/pricing-v2/legacy-preview` — V1 Python Decimal kalkulyatori, unsaved admin forma uchun

## Chegaralar va kelgusi ishlar

- Go V2 preview uchun admin **sinov** masofa/vaqt kiritadi, bu OSRM'dan tasdiqlangan haqiqiy buyurtma marshruti emas; real quote oqimida OSRM yo‘li va vaqtini backendning o‘zi olib beradi.
- Go V2 narxi hech qachon `orders.price`ga yozilmaydi. Keyingi bosqich: pricing quote, tarif snapshot, shadow mode va xavfsiz rollout.
- V1 mavjud `_overload_warning` qaytaradi. Real buyurtmada sig‘imdan oshgan yukni qat’iy bloklash — alohida product/operations o‘zgarishi bo‘lishi kerak; V2 preview hozir sig‘imdan oshgan yukni rad etadi.
- Bitta truck_type uchun har safar faqat bitta so‘nggi draft tahrirlanadi, publish qilingandan keyin keyingi versiya yaratiladi; adminlar parallel saqlaganda truck satri row-lock bilan himoyalangan.
- Configured empty-run koeffitsiyentlari bo‘yicha real transport sarfi taxmin qilinmaydi. Xarajatlarni admin o‘zi kiritishi kerak.
