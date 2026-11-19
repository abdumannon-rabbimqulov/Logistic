// Backend sxemalariga mos TS interfeyslar (order/schemas.py, driver/schemas.py, users/schemas.py).
// Numeric (Decimal) maydonlar JSON orqali string yoki number bo'lib kelishi mumkin — shuning
// uchun hammasi `number` deb belgilangan va api/client.ts orqali normalizatsiya qilinadi.

export type UserRole = 'admin' | 'sender' | 'driver' | 'guest' | 'dispatcher' | 'manager';

export interface DriverCreateInput {
  truck_type_id: number;
  truck_number: string;
  truck_year?: number;
  /** Ixtiyoriy — ilovada so'ralmaydi, joylashuv jonli GPS orqali aniqlanadi. */
  current_city?: string;
  current_region?: string;
  phone_number?: string;
}

// POST /drivers/profile (yaratish) javobi — driver/schemas.py DriverResponse
export interface DriverProfile {
  id: number;
  user_id: number;
  truck_type_id: number;
  truck_number: string;
  truck_year: number | null;
  current_city: string | null;
  current_region: string | null;
  rating: number;
  total_trips: number;
  cancel_count: number;
  on_time_percent: number;
  is_available: boolean;
  is_blocked: boolean;
  block_reason: string | null;
  created_at: string;
  updated_at: string;
}

// GET/PATCH /drivers/me javobi — driver/schemas.py DriverProfileResponse (boshqacha shakl!)
export interface DriverCabinet {
  id: number;
  user_id: number;
  name: string;
  rating: number;
  balance: string;
  balance_amount: number;
  currency: string;
  user_status: 'LIVE' | 'OFFLINE';
  gps_status: 'ON' | 'OFF';
  phone_number: string | null;
  truck_type_id: number;
  truck_type_name: string | null;
  truck_number: string;
  truck_year: number | null;
  current_city: string | null;
  current_region: string | null;
  is_available: boolean;
  available_from_date: string | null;
  total_trips: number;
  on_time_percent: number;
  is_blocked: boolean;
}

export interface GoOnlineInput {
  is_available: boolean;
  current_city?: string;
  current_region?: string;
  available_from_date?: string | null;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  role: UserRole;
  user_id: number;
  status?: 'need_driver_profile';
  message?: string;
}

export interface UserProfile {
  id: number;
  username: string | null;
  full_name: string;
  email: string | null;
  phone_number: string | null;
  role: UserRole;
  language: string;
  is_active: boolean;
  is_banned: boolean;
  balance: number;
  created_at: string;
  updated_at: string;
  /** Brauzerdan (telefon + parol) kirish uchun parol o'rnatilganmi. */
  has_password: boolean;
}

export interface TruckType {
  id: number;
  name: string;
  max_weight: number;
  max_volume: number;
  length: number | null;
  width: number | null;
  height: number | null;
  pallet_capacity: number | null;
  base_price: number;
  price_per_km: number;
  min_price: number | null;
  /** 1 tonna-km narxi (UZS). 0 — og'irlik narxga ta'sir qilmaydi. */
  price_per_ton_km: number;
  image_url: string | null;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

export type WaypointType = 'PICKUP' | 'DELIVERY' | 'TRANSIT';
export type WaypointStatus = 'PENDING' | 'ARRIVED' | 'COMPLETED' | 'SKIPPED';
export type OrderStatus = 'SCHEDULED' | 'PENDING' | 'ACCEPTED' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED';

export interface OrderWaypoint {
  id: number;
  order_id: number;
  sequence: number;
  type: WaypointType;
  status: WaypointStatus;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  contact_name: string | null;
  contact_phone: string | null;
  created_at: string;
  /** Haydovchi "Yetib keldim" bosgan payt. */
  arrived_at: string | null;
  /** Nuqta yakunlangan (yuk ortilgan/topshirilgan) payt. */
  completed_at: string | null;
  /** Qadam tasdiqlanganda o'lchangan masofa (metr) — GPS isboti. */
  confirmed_distance_m: number | null;
  confirmed_accuracy_m: number | null;
  /** To'ldirilgan bo'lsa — qadam admin tomonidan qo'lda tasdiqlangan (geofence'siz). */
  override_by_user_id: number | null;
  override_reason: string | null;
}

/** PATCH /orders/{id}/waypoints/{wid} — nuqtadagi qadamni belgilash.
 *  Koordinata tugma bosilgan paytda olinadi (geofence uchun asosiy manba). */
export interface WaypointProgressInput {
  status: WaypointStatus;
  latitude?: number;
  longitude?: number;
  accuracy?: number;
  /** Faqat admin: GPS nosoz bo'lganda qadamni qo'lda tasdiqlash sababi. */
  override_reason?: string;
}

export interface OrderWaypointInput {
  sequence: number;
  type: WaypointType;
  address?: string;
  latitude?: number;
  longitude?: number;
  contact_name?: string;
  contact_phone?: string;
}

// GET /orders va GET /orders/available/list shu yengil sxemani qaytaradi — manzillar/waypoint YO'Q.
/** Ro'yxat kartasi uchun nuqta (kontaktlarsiz) — order/schemas.py OrderPointSummary. */
export interface OrderPointSummary {
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  status: WaypointStatus;
}

export interface OrderListItem {
  id: number;
  required_truck_type_id: number | null;
  origin: OrderPointSummary | null;
  destination: OrderPointSummary | null;
  cargo_name: string;
  weight: number;
  price: number;
  currency: string;
  status: OrderStatus;
  pickup_at: string;
  driver_id: number | null;
  overload_warning: string | null;
  created_at: string;
  /** COMPLETED bo'lganda to'ldiriladi — daromad hisoboti shu sana bo'yicha guruhlanadi. */
  completed_at: string | null;
}

/** Yuk manzilga yetib borgandan keyingi tushirish sharti (order/models.py UnloadingMode).
 *  Ixtiyoriy — mijoz tanlamasa `null` bo'ladi va hech qanday shart qo'yilmaydi. */
export type UnloadingMode = 'IMMEDIATE' | 'HOURS' | 'DAY';

export interface Order {
  id: number;
  customer_id: number;
  driver_id: number | null;
  cargo_name: string;
  weight: number;
  volume: number | null;
  pickup_at: string;
  unloading_mode: UnloadingMode | null;
  unloading_wait_hours: number | null;
  departure_at: string | null;
  required_truck_type_id: number;
  total_distance_km: number | null;
  price: number;
  original_price: number | null;
  currency: string;
  status: OrderStatus;
  dispatch_round: number;
  price_bump_requested_at: string | null;
  /** To'ldirilgan bo'lsa — haydovchi qidiruvi hali boshlanmagan va shu paytda
   *  boshlanadi (kelajakka rejalashtirilgan yuk). `null` — qidiruv ketmoqda. */
  dispatch_starts_at: string | null;
  /** To'ldirilgan bo'lsa — sender qidiruvni qo'lda to'xtatgan: yangi taklif yuborilmaydi
   *  va aynan shu paytda narxni o'zgartirish mumkin. */
  dispatch_paused_at: string | null;
  overload_warning: string | null;
  completed_at: string | null;
  /** Haydovchi "Start" bosgan payt (yuk olishga yo'lga chiqdi). */
  started_at?: string | null;
  cancelled_at?: string | null;
  cancel_reason?: string | null;
  created_at: string;
  updated_at: string;
  waypoints: OrderWaypoint[];
}

/** Bir foydalanuvchi bilan bog'lanish uchun kerakli minimal ma'lumot (order/schemas.py TelegramContact). */
export interface TelegramContact {
  full_name: string;
  phone_number: string | null;
  username: string | null;
  /** Tayyor `https://t.me/<username>` havolasi — `username` bo'lmasa `null`. */
  telegram_url: string | null;
}

/** Haydovchi kontakti — mashina ma'lumoti bilan birga (order/schemas.py OrderDriverContact). */
export interface OrderDriverContact extends TelegramContact {
  truck_number: string;
  truck_type_name: string | null;
  rating: number;
}

/** GET /orders/{id}/driver-location va WS `location`/`update` hodisasi. */
export interface OrderDriverLocation {
  lat: number;
  lon: number;
  accuracy: number | null;
  ts: string;
}

export interface OrderDetail extends Order {
  origin: OrderWaypoint | null;
  destination: OrderWaypoint | null;
  current_waypoint: OrderWaypoint | null;
  /** Buyurtmaga haydovchi biriktirilgan bo'lsa to'ldiriladi — sender shu orqali
   *  haydovchi bilan bog'lanadi (tel/telegram). */
  driver_contact: OrderDriverContact | null;
  /** Haydovchi shu orqali buyurtmachi (sender) bilan bog'lanadi. */
  sender_contact: TelegramContact | null;
}

export interface OrderCreateInput {
  cargo_name: string;
  weight: number;
  volume?: number;
  pickup_at: string;
  required_truck_type_id: number;
  unloading_mode?: UnloadingMode;
  /** Faqat `HOURS` bilan birga yuboriladi — backend aks holda 422 qaytaradi. */
  unloading_wait_hours?: number;
  waypoints: OrderWaypointInput[];
}

// ── Avtomatik dispatch (haydovchiga navbat bilan yuboriladigan taklif) ──────────────
export type DispatchMatchType = 'gps' | 'region';
export type DispatchAttemptStatus = 'pending' | 'accepted' | 'rejected' | 'expired' | 'cancelled';

// GET /orders/dispatch/active javobidagi `order` xulosasi (order/schemas.py DispatchOrderSummary).
export interface DispatchOrderSummary {
  cargo_name: string;
  weight: number;
  price: number;
  currency: string;
  origin_address: string | null;
  destination_address: string | null;
  /** A→B marshrut uzunligi (buyurtmaning o'z masofasi) — `DispatchAttemptResponse.distance_km`
   *  bilan chalkashtirmaslik kerak: u haydovchidan A nuqtagacha bo'lgan masofa. */
  total_distance_km: number | null;
  origin_latitude: number | null;
  origin_longitude: number | null;
  destination_latitude: number | null;
  destination_longitude: number | null;
  /** OSRM marshrut chizig'i: [[latitude, longitude], ...] — xaritada chiziladi. */
  route_geometry: [number, number][];
}

// GET /orders/dispatch/active — null yoki joriy faol taklif (order/schemas.py DispatchAttemptResponse).
export interface DispatchAttemptResponse {
  id: number;
  order_id: number;
  driver_id: number;
  round_number: number;
  match_type: DispatchMatchType;
  /** Haydovchidan yuk ortish nuqtasigacha ("sizgacha") masofa — marshrut uzunligi EMAS. */
  distance_km: number | null;
  status: DispatchAttemptStatus;
  sent_at: string;
  expires_at: string;
  order: DispatchOrderSummary | null;
}

// ── Admin panel (Admin_panel/schemas.py) ────────────────────────────────────────────
export interface OrdersByDay {
  date: string; // YYYY-MM-DD
  count: number;
}

export interface AdminDashboardStats {
  users_total: number;
  users_today: number;
  drivers_total: number;
  drivers_online: number;
  drivers_live_gps: number;
  orders_total: number;
  orders_today: number;
  /** Yakunlangan buyurtmalar bo'yicha umumiy aylanma (DB tomonda SUM bilan hisoblanadi). */
  revenue_total: number;
  orders_by_status: Record<string, number>;
  orders_last_7_days: OrdersByDay[];
}

export interface AdminUserListItem {
  id: number;
  username: string | null;
  full_name: string;
  email: string | null;
  phone_number: string | null;
  role: string | null;
  language: string;
  is_active: boolean;
  is_banned: boolean;
  balance: number;
  created_at: string;
  updated_at: string;
}

export interface AdminUserList {
  total: number;
  items: AdminUserListItem[];
}

export interface AdminUserUpdate {
  role?: UserRole;
  is_banned?: boolean;
  is_active?: boolean;
  language?: string;
  full_name?: string;
}

/** GET /system/drivers/monitor — xarita monitoringi (Admin_panel MonitorActiveOrder) */
export interface MonitorActiveOrder {
  id: number;
  cargo_name: string;
  weight: number;
  volume: number | null;
  price: number;
  currency: string;
  status: OrderStatus;
  origin_address: string | null;
  destination_address: string | null;
  current_waypoint_address: string | null;
  total_waypoints: number;
  completed_waypoints: number;
}

export interface DriverMonitorItem {
  driver_id: number;
  user_id: number;
  full_name: string | null;
  phone_number: string | null;
  truck_type_name: string | null;
  truck_number: string;
  is_available: boolean;
  is_blocked: boolean;
  block_reason: string | null;
  rating: number;
  total_trips: number;
  /** Hozir jonli GPS translyatsiya qilyapti (Redis'da yozuvi bor) */
  online: boolean;
  /** Faol (ACCEPTED/IN_PROGRESS) buyurtmasi bor — "yukli" */
  busy: boolean;
  latitude: number | null;
  longitude: number | null;
  location_source: 'live' | 'last_known' | null;
  location_at: string | null;
  active_order: MonitorActiveOrder | null;
}

export interface DriverLocationItem {
  driver_id: number;
  user_id: number | null;
  full_name: string | null;
  truck_number: string | null;
  truck_type_id: number | null;
  lat: number;
  lon: number;
  ts: string;
  expires_at: string | null;
  /** WS "update" xabarida keladi: haydovchi jonli translyatsiyani to'xtatdi (ro'yxatdan olib tashlanadi). */
  stopped?: boolean;
}

export interface CommissionSettings {
  commission_percent: number;
  updated_at: string;
}

/** GET/PATCH /system/settings/pricing — sender narxni qo'lda qancha tushira olishi.
 *  Bu chegara `PATCH /orders/{id}/price` da tekshiriladi: undan past narx 400 qaytaradi. */
export interface PricingSettings {
  sender_max_discount_percent: number;
  updated_at: string;
}

/** GET /system/drivers — balans va blok holati bilan (Admin_panel AdminDriverListItem) */
export interface AdminDriverListItem {
  driver_id: number;
  user_id: number;
  full_name: string | null;
  phone_number: string | null;
  truck_number: string;
  truck_type_id: number;
  balance: number;
  is_blocked: boolean;
  block_reason: string | null;
  /** true — balans manfiy bo'lgani uchun tizim avtomatik bloklagan (admin qo'lda emas) */
  blocked_for_debt: boolean;
  is_available: boolean;
  verification_status: string;
  created_at: string;
}

export interface AdminDriverList {
  total: number;
  items: AdminDriverListItem[];
}

/** POST /orders/{id}/assign-driver javobidagi haydovchi bloki */
export interface AssignedDriverInfo {
  driver_id: number;
  user_id: number;
  full_name: string | null;
  phone_number: string | null;
  truck_number: string;
  truck_type_id: number;
  is_available: boolean;
  is_blocked: boolean;
  verification_status: string;
  rating: number;
  total_trips: number;
}

export interface OrderAssignDriverResponse {
  order: OrderDetail;
  driver: AssignedDriverInfo;
}

/** PATCH /system/orders/{id} — admin moderatsiyasi (Admin_panel AdminOrderUpdate) */
export interface AdminOrderUpdate {
  status?: OrderStatus;
  cargo_name?: string;
  weight?: number;
  price?: number;
  currency?: string;
}

/** "Daromad" ekranidagi bitta qator (GET /drivers/me/earnings).
 *
 *  `commission_amount` — platforma ushlab qolgan summa, MUSBAT son (bazada u
 *  manfiy saqlanadi, chunki balansdan yechiladi). `net_amount` — haydovchi
 *  qo'liga tushadigan sof summa. */
export interface DriverEarning {
  order_id: number;
  cargo_name: string;
  origin_address: string | null;
  destination_address: string | null;
  gross_amount: number;
  commission_amount: number;
  net_amount: number;
  currency: string;
  completed_at: string | null;
}

/** Balans harakati (GET /system/users/{id}/balance/transactions) */
export interface BalanceTransaction {
  id: number;
  user_id: number;
  type: string;
  amount: number;
  balance_after: number;
  order_id: number | null;
  created_by_admin_id: number | null;
  note: string | null;
  created_at: string;
}

export interface DriverUnblockPayload {
  /** Blokdan chiqarish bilan birga balansga qo'shiladigan summa (qarzni yopish uchun) */
  top_up_amount?: number;
  note?: string;
}

// POST/PATCH /drivers/truck-types uchun kirish (driver/schemas.py TruckTypeCreate/Update)
export interface TruckTypeInput {
  name: string;
  max_weight: number;
  max_volume: number;
  length?: number | null;
  width?: number | null;
  height?: number | null;
  pallet_capacity?: number | null;
  base_price: number;
  price_per_km: number;
  min_price?: number | null;
  price_per_ton_km?: number;
  image_url?: string | null;
  description?: string | null;
  is_active?: boolean;
}

export interface GeocodeSuggestion {
  address: string;
  latitude: number;
  longitude: number;
}

export interface ReverseGeocodeResponse {
  address: string | null;
  latitude: number;
  longitude: number;
}

export interface PriceEstimateLocation {
  address?: string;
  latitude?: number;
  longitude?: number;
}

/** Bitta "narxni oshirish" tugmasi — qiymatlarni backend beradi
 *  (services/pricing.py QUICK_PRICE_INCREMENTS), frontend hisoblamaydi. */
export interface QuickPriceOption {
  increment: number;
  price: number;
  currency: string;
}

/** GET /orders/{id}/price-options javobi. */
export interface OrderPriceOptionsResponse {
  order_id: number;
  currency: string;
  base_price: number;
  current_price: number;
  min_allowed_price: number;
  max_discount_percent: number;
  quick_price_options: QuickPriceOption[];
}

export interface PriceEstimateOption {
  truck_type_id: number;
  name: string;
  image_url: string | null;
  price: number;
  currency: string;
}

export interface PriceEstimateResponse {
  origin_address: string | null;
  origin_latitude: number;
  origin_longitude: number;
  destination_address: string | null;
  destination_latitude: number;
  destination_longitude: number;
  distance_km: number;
  duration_min: number;
  // OSRM marshrut chizig'i: [[latitude, longitude], ...] — xaritada ko'rsatiladi
  route_geometry: [number, number][];
  options: PriceEstimateOption[];
}

// ─── Support mikroservisi (yordam chati) ─────────────────────────────────────
// Manba: support_service/schemas.py va support_service/models.py.
// Har foydalanuvchiga BITTA chat (tarixiy nomi "ticket"): barcha savollar shu yerda.
// DIQQAT: bu xizmat asosiy app'dan alohida — yo'llari `/api` ostida emas, `/support`
// prefiksida va u faqat `SECRET_KEY` hamda RabbitMQ orqali bog'langan.

/** `closed` — eski qiymat (birlashtirishdan oldingi), endi o'rnatilmaydi. */
export type TicketStatus = 'open' | 'in_progress' | 'resolved' | 'closed';
export type TicketPriority = 'low' | 'normal' | 'high' | 'urgent';
export type AttachmentKind = 'image' | 'video' | 'document';

/** Biriktirma. `url` — imzolangan, qisqa muddatli havola (token'siz ochiladi). */
export interface TicketAttachment {
  id: number;
  filename: string;
  content_type: string;
  kind: AttachmentKind;
  size: number;
  url: string;
}

/** Ticket ichidagi bitta xabar. `is_system: true` bo'lganda muallif yo'q — bu
 *  `order.*` hodisasidan avtomatik tushgan yozuv (support RabbitMQ'dan oladi). */
export interface TicketMessage {
  id: number;
  ticket_id: number;
  author_user_id: number | null;
  author_role: string | null;
  author_name: string | null;
  is_system: boolean;
  body: string;
  /** Xabar qaysi buyurtma haqida (buyurtma sahifasidan yozilganda). */
  order_id: number | null;
  created_at: string;
  attachments: TicketAttachment[];
}

export interface TicketMessagePreview {
  body: string;
  author_role: string | null;
  author_name: string | null;
  is_system: boolean;
  has_attachments: boolean;
  created_at: string;
}

export interface TicketListItem {
  id: number;
  user_id: number;
  user_role: string | null;
  user_name: string | null;
  order_id: number | null;
  subject: string;
  status: TicketStatus;
  priority: TicketPriority;
  assigned_to: number | null;
  assigned_name: string | null;
  created_at: string;
  updated_at: string;
  last_message_at: string;
  /** So'rovchi nuqtai nazaridan: egasi uchun — xodim javoblari, xodim uchun — egasining xabarlari. */
  unread_count: number;
  last_message: TicketMessagePreview | null;
  /** Shu foydalanuvchi o'tkaza oladigan holatlar (support_service/rules.py). */
  allowed_statuses: TicketStatus[];
}

export interface TicketPage {
  items: TicketListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TicketDetail extends TicketListItem {
  body: string;
  /** Oxirgi xabarlar (o'sish tartibida); eskilari — `listTicketMessages`. */
  messages: TicketMessage[];
  has_more_messages: boolean;
}

export interface TicketMessagePage {
  items: TicketMessage[];
  has_more: boolean;
}

/** Javob yozilgandan keyin — yangi xabar va murojaatning yangilangan holati
 *  (masalan xodim javobidan keyin OPEN → IN_PROGRESS). */
export interface TicketMessageCreated extends TicketMessage {
  ticket: TicketListItem;
}

export interface SupportUnreadSummary {
  tickets: number;
  messages: number;
}

/** WS orqali keladigan murojaat ko'rinishi — ko'ruvchiga bog'liq maydonlarsiz. */
export type TicketPublic = Omit<TicketListItem, 'unread_count' | 'allowed_statuses'>;

/** `GET /support/conversation` — o'z chatim; hali yozmagan bo'lsam `null`. */
export interface SupportConversationResponse {
  conversation: TicketDetail | null;
}

export type SupportSocketEvent =
  | { type: 'hello'; user_id: number }
  | { type: 'ping' }
  | { type: 'message.created'; ticket_id: number; message: TicketMessage; ticket: TicketPublic }
  | { type: 'ticket.created'; ticket: TicketPublic }
  | { type: 'ticket.updated'; ticket: TicketPublic }
  // WS orqali yuborilgan xabarga javob (`client_id` — yuboruvchining o'z belgisi).
  | { type: 'message.ack'; client_id: string; message: TicketMessageCreated }
  | { type: 'message.error'; client_id: string; status: number; detail: unknown };

// ─── Menejer paneli ──────────────────────────────────────────────────────────
// Manba: manager/schemas.py. DIQQAT: bu sxemalarda NARX MAYDONLARI ATAYLAB YO'Q —
// menejer moliyaviy ma'lumotni ko'rmasligi kerak va backend uni uch qatlamda
// (endpoint, sxema, `strip_finance_fields`) kesib tashlaydi. Shuning uchun bu
// yerga ham price/commission kabi maydonlar QO'SHILMASIN.

export interface ManagerOrderListItem {
  id: number;
  cargo_name: string;
  weight: number;
  status: OrderStatus;
  pickup_at: string;
  customer_id: number;
  driver_id: number | null;
  required_truck_type_id: number;
  overload_warning: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ManagerWaypoint {
  id: number;
  sequence: number;
  type: WaypointType;
  status: WaypointStatus;
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  contact_name: string | null;
  contact_phone: string | null;
  arrived_at: string | null;
  completed_at: string | null;
}

export interface ManagerOrderDetail {
  id: number;
  customer_id: number;
  driver_id: number | null;
  cargo_name: string;
  weight: number;
  volume: number | null;
  status: OrderStatus;
  required_truck_type_id: number;
  pickup_at: string;
  departure_at: string | null;
  total_distance_km: number | null;
  dispatch_round: number;
  overload_warning: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  created_at: string;
  updated_at: string;
  waypoints: ManagerWaypoint[];
}

/** Buyurtmaga biriktirish mumkin bo'lgan mashina. Alohida `trucks` jadvali yo'q —
 *  mashina haydovchi profilining bir qismi, shuning uchun kalit `driver_id`. */
export interface AvailableTruck {
  driver_id: number;
  truck_number: string;
  truck_type_id: number;
  truck_type_name: string;
  truck_year: number | null;
  max_weight: number | null;
  max_volume: number | null;
  rating: number;
  total_trips: number;
  is_available: boolean;
  is_blocked: boolean;
  verification_status: string;
  current_city: string | null;
  current_region: string | null;
}

export interface AssignTruckResponse {
  order: ManagerOrderDetail;
  truck: AvailableTruck;
}

/** PATCH /orders/{id} — buyurtma egasi tahrirlay oladigan maydonlar.
 *  Manba: order/schemas.py OrderUpdate. Tizim boshqaradigan maydonlar (status, narx,
 *  driver_id, masofa) ATAYLAB yo'q va serverda `extra="forbid"` bilan taqiqlangan —
 *  bu yerga ham qo'shilmasin. */
export interface OrderUpdateInput {
  cargo_name?: string;
  weight?: number;
  volume?: number;
  pickup_at?: string;
  required_truck_type_id?: number;
}

// ── Server monitoringi (`GET /system/monitoring`, services/monitoring.py) ─────────
export type HealthStatus = 'ok' | 'warn' | 'critical';

export interface MonitoringPoint {
  /** Bo'lak boshlanishi, unix soniya. */
  t: number;
  rpm: number;
  avg_ms: number | null;
  p95_ms: number | null;
  errors_5xx: number;
  errors_4xx: number;
}

export interface MonitoringRouteRow {
  route: string;
  count: number;
  avg_ms: number | null;
  errors_4xx: number;
  errors_5xx: number;
}

export interface MonitoringRequests {
  minutes: number;
  step_minutes: number;
  bucket_edges_ms: number[];
  series: MonitoringPoint[];
  totals: {
    requests: number;
    rpm: number;
    errors_4xx: number;
    errors_5xx: number;
    error_rate_5xx: number;
    avg_ms: number | null;
    p50_ms: number | null;
    p95_ms: number | null;
    p99_ms: number | null;
    histogram: number[];
  };
  slowest_routes: MonitoringRouteRow[];
  error_routes: MonitoringRouteRow[];
  busiest_routes: MonitoringRouteRow[];
  /** Oxirgi server xatolari, eng yangisi birinchi (services/metrics.py record_error). */
  recent_errors?: MonitoringErrorEntry[];
}

export interface MonitoringErrorEntry {
  /** unix soniya */
  ts: number;
  method: string;
  path: string;
  status: number;
  exc_type: string;
  message: string;
  request_id: string;
}

export interface MonitoringComponentBase {
  status: HealthStatus;
  issues: string[];
  check_ms: number;
}

export interface MonitoringQueueRow {
  queue: string;
  consumer: string;
  messages: number | null;
  consumers: number | null;
  status: HealthStatus;
}

// Komponent tekshiruvi yiqilsa faqat `status`/`issues` keladi — shuning uchun
// qolgan maydonlar ixtiyoriy.
export interface MonitoringComponents {
  api: MonitoringComponentBase & {
    in_flight?: number;
    process_uptime_sec?: number;
    process_rss?: number | null;
    db_pool?: { size: number; checked_out: number; overflow: number };
  };
  server: MonitoringComponentBase & {
    cpu_percent?: number;
    cpu_cores?: number;
    load_avg?: [number, number, number];
    mem_total?: number;
    mem_used?: number;
    mem_percent?: number | null;
    swap_total?: number;
    swap_used?: number;
    disk_total?: number;
    disk_used?: number;
    disk_percent?: number | null;
    uptime_sec?: number;
  };
  postgres: MonitoringComponentBase & {
    ping_ms?: number;
    connections?: number;
    active_queries?: number;
    max_connections?: number;
    size_bytes?: number;
    cache_hit_percent?: number | null;
    deadlocks?: number;
    longest_query_sec?: number;
  };
  redis: MonitoringComponentBase & {
    ping_ms?: number;
    used_memory?: number;
    connected_clients?: number;
    ops_per_sec?: number;
    hit_rate_percent?: number | null;
    uptime_sec?: number;
  };
  rabbitmq: MonitoringComponentBase & {
    queues?: MonitoringQueueRow[];
    workers?: Record<string, number | null>;
  };
  osrm: MonitoringComponentBase & { latency_ms?: number };
  support: MonitoringComponentBase & { latency_ms?: number };
  business: MonitoringComponentBase & {
    orders_searching?: number;
    orders_stuck?: number;
    orders_waiting_price?: number;
    orders_created_last_hour?: number;
    dispatch_attempts_last_hour?: Record<string, number>;
  };
}

export interface MonitoringOverview {
  generated_at: string;
  status: HealthStatus;
  components: MonitoringComponents;
  requests: MonitoringRequests;
}

// ── Jonli yuk xaritasi (GET /orders/live-map) ─────────────────────────────
// Shaxsiy ma'lumot (haydovchi ismi, davlat raqami, telefon, ID lar) backendda
// ATAYLAB qaytarilmaydi.

export type LiveMapMode = 'in_transit' | 'empty' | 'all';

export interface RegionItem {
  id: number;
  name: string;
}

export interface LiveMapItem {
  marker_id: string;
  lat: number;
  lon: number;
  has_cargo: boolean;
  truck_type_id: number | null;
  truck_type_name: string | null;
  truck_type_image_url: string | null;
  truck_max_weight: number | null;
  current_region: string | null;
  cargo_name: string | null;
  weight: number | null;
  load_percent: number | null;
  pickup_address: string | null;
  pickup_lat: number | null;
  pickup_lon: number | null;
  pickup_region: string | null;
  delivery_address: string | null;
  delivery_lat: number | null;
  delivery_lon: number | null;
  delivery_region: string | null;
  distance_km: number | null;
  price: number | null;
  price_per_ton: number | null;
  currency: string;
}

export interface LiveMapStats {
  period_days: number;
  count: number;
  min_price: number | null;
  avg_price: number | null;
  max_price: number | null;
  avg_price_per_ton: number | null;
  avg_weight: number | null;
}

export interface LiveMapResponse {
  items: LiveMapItem[];
  stats: LiveMapStats;
  generated_at: string;
}

export interface LiveMapFilter {
  mode: LiveMapMode;
  fromRegion: number | null;
  toRegion: number | null;
  truckTypeId: number | null;
}

/** GET /orders/{id}/eta — haydovchi joylashuvining yangiligi va keyingi nuqtagacha ETA. */
export interface OrderEta {
  location_updated_at: string | null;
  location_age_sec: number | null;
  location_stale: boolean;
  gps_lost_reason: 'denied' | 'unavailable' | 'timeout' | string | null;
  target_type: WaypointType | null;
  distance_km: number | null;
  duration_min: number | null;
}
