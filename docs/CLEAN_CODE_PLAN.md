# Clean code rejasi: takrorlangan kodni yo'qotish

Tahlil 2026-11-19 da qilingan:
- backend uchun `pylint duplicate-code`, `vulture` va qo'lda qidiruv;
- frontend uchun import grafi va qo'lda qidiruv.

Umumiy holat yaxshi: katta nusxa-ko'chirilgan bloklar yo'q, frontendda ishlatilmayotgan fayl yoki eksport topilmadi. Takrorlanish asosan kichik yordamchi funksiyalarda, yorliq ro'yxatlarida va mikroservislar chegarasida.

Allaqachon olib tashlangan (`3ffb237`):
- ishlamaydigan `scripts/seed_uzbekistan_geo.py` va `scripts/geo_utils.py`;
- ishlatilmagan sxemalar: `DriverDocument*`, `DocumentType`, `DriverTripScope`, `OrderStatusUpdate`, `TelegramWebAppLoginRequest`.

## 1. Eski GPS WebSocket'larini core'dan olib tashlash (eng katta takror)
- **Muammo:** `tracking_service` endi bu ikki WebSocket'ni qabul qiladi:
  - `driver/router.py: websocket_driver_location`;
  - `order/router.py: order_driver_location_ws`.

  Core'dagi nusxalari nginx/Vite orqali ishlatilmaydi, lekin ~150 qator bo'lib turibdi. Ular bilan birga quyidagi takrorlar ham bor:
  - `parse_fix_time` / `is_stale_fix`: `driver/router.py` va `tracking_service/fixes.py`;
  - token tozalash: `_normalize_ws_token` va `tracking_service/main.py: _token`.
- **Qilinadi:** tracking prod'da ishlashi tasdiqlangach, core endpointlari va ularning yordamchilari o'chiriladi. `services/live_location.py` dan faqat o'qish funksiyalari qoladi, `update_driver_location` va `mark_gps_lost` olib tashlanadi.
- **Shart:** tracking deploy qilingan va haydovchi GPS'i u orqali kelayotgani ko'rilgan bo'lishi kerak.

## 2. Telegram yuborish: 4 joy o'rniga 2 ta
| Joy | Usul |
|---|---|
| `notification_service/telegram.py` | async httpx — asosiy |
| `services/notifications.py` | async httpx — dispatch takliflari uchun `message_id` kerak |
| `utils/admin_alerts.py` | **sinxron `urllib` + thread** — eskirgan |
| `handlers/` (aiogram bot) | bot o'zi |

- **Qilinadi:** `utils/admin_alerts._send_sync` o'rniga `services/notifications.send_telegram_message`.
- **Keyin:** `location_watch` va `start_reminders` dagi admin xabarlari event orqali `notification_service`'ga o'tadi. Core'da bevosita yuborish faqat dispatch takliflari uchun qoladi.

## 3. Kichik yordamchi funksiyalar
| Takror | Joylari | Bitta joyga |
|---|---|---|
| `_staff_ids()` (admin + menejerlar) | `services/location_watch.py`, `services/start_reminders.py` | `services/staff.py` |
| ISO vaqtni o'qish (`_parse_iso`, `_parse_ts`) | `services/order_eta.py`, `services/live_location_sync.py` | `utils/time.py` |
| Redis payload'dan haydovchi nuqtasi | `order_eta.latest_driver_fix`, `public_map`, `dispatch` | `order_eta.latest_driver_fix` ni hamma ishlatadi |
| "Joylashuv yangimi" chegaralari (2 daqiqa / 6 soat) | `geofence._is_fresh`, `dispatch.LAST_LOCATION_MAX_AGE_SEC`, `public_map.LAST_KNOWN_MAX_AGE`, `order_eta.is_fix_stale` | bitta modul, nomlangan konstantalar |

## 4. Status yorliqlari (backend)
- **Takror:** `services/order_flow.py` (`_ORDER_STATUS_LABEL`, `_WAYPOINT_STATUS_LABEL`) va `support_service/main.py` (`_STATUS_LABEL`).
- **Qilinadi:** core'da bitta `order/labels.py`. Support alohida servis bo'lgani uchun o'z nusxasini saqlaydi, lekin moslik `tests/test_event_contract.py` da tekshiriladi.

## 5. Frontend
| Takror | Joylari | Qilinadi |
|---|---|---|
| Nuqta turi/holati yorliqlari | `utils/orderStatus.ts` + 3 nusxa: `DriverActiveOrderPage.tsx`, `admin/components/OrderWaypointsPanel.tsx`, `manager/pages/ManagerOrderDetailPage.tsx` | hammasi `utils/orderStatus.ts` dan |
| Buyurtma statusi ro'yxati | `admin/pages/AdminOrders.tsx: STATUS_OPTIONS`, `admin/components/StatusBadge.tsx` | `ORDER_STATUS_META` dan quriladi |
| Yandex xaritasini yaratish + ResizeObserver + destroy | `YandexMap`, `LiveMapPage`, `DriversMap`, `MapPointPicker` (4 joy) | `hooks/useYandexMap.ts` |
| WebSocket manzilini qurish (`http→ws`) | `api/admin.ts`, `api/orders.ts`, `hooks/useLiveLocation.ts` | `api/client.ts: wsUrl(path)` |
| Sana/vaqt formati (`toLocaleString('uz-UZ', …)`) | ~29 joyda | `utils/format.ts: formatTime`, `formatDateTime` |

## 6. Mikroservis chegarasidagi "ataylab" takrorlar
- **Qanday takrorlar:** `services/queue.py` va `support_service/queue.py` (RabbitMQ ulanishi); `notification_service/contracts.py` (event nomlari).
- **Nega ataylab:** servislar bir-birining kodini import qilmasligi kerak.
- **Qilinadi:** kod nusxalari qoladi, lekin hammasi bitta `contracts/` paketidan olinadi (JSON Schema). Shu paket Go'ga o'tishda ham ishlatiladi.

## 7. Sinov hisoblari (prod)
- **Muammo:** `scripts/seed_test_users.py` prod'da paroli `1111` bo'lgan 10 ta sinov hisobini yaratadi.
- **Qilinadi:** real foydalanuvchilar bilan ishlay boshlagach, prod'da `--delete` bilan o'chiriladi, keyin skriptning o'zi ham o'chiriladi.

## Holat
- **Bajarildi (2026-11-19):** 3, 4 va 5-bandlar.
  - backend: `services/staff.py`, `utils/time.py`, `LAST_KNOWN_LOCATION_MAX_AGE_SEC`, `order/labels.py`;
  - frontend: yorliqlar `utils/orderStatus.ts` dan, `hooks/useYandexMap.ts`, `api/client.ts: wsUrl`, `utils/format.ts` dagi sana va pul formatlari.
- **Qolgan:** 1, 2, 6, 7.

## Bajarish tartibi
**3 → 4 → 5 → 2 → 1 → 6 → 7.**
- 3, 4 va 5 xavfsiz, mahalliy o'zgarishlar: har biri alohida commit, testlar va build bilan.
- 1 tracking prod'da tasdiqlangandan keyin.
- 7 foydalanuvchi qaroriga bog'liq.

Har qadamdan keyin `pytest`, `npx tsc -b`, `npm run lint` va `npm run build` ishga tushiriladi.
