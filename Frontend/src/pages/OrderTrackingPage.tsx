import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import {
  bumpPrice,
  cancelOrder,
  getOrder,
  getOrderEta,
  getPriceOptions,
  pauseDispatch,
  resumeDispatch,
} from '../api/orders';
import { BottomSheet } from '../components/BottomSheet';
import { CustomPriceSheet } from '../components/CustomPriceSheet';
import { OrderEditSheet } from '../components/OrderEditSheet';
import { OrderStatusBadge } from '../components/OrderStatusBadge';
import { OrderStepper } from '../components/OrderStepper';
import { BackIcon, PhoneIcon, SendIcon, StarIcon } from '../components/icons';
import { YandexMap } from '../components/YandexMap';
import { useOrderDriverLocation } from '../hooks/useOrderDriverLocation';
import type { OrderDetail, OrderEta, QuickPriceOption } from '../types/api';
import { formatClock, formatEta, formatPrice, formatShortDateTime, routeLabel, shortAddress, unloadingLabel } from '../utils/format';
import {
  FINAL_ORDER_STATUSES,
  WAYPOINT_STATUS_LABEL,
  WAYPOINT_TYPE_LABEL,
  orderStatusMeta,
} from '../utils/orderStatus';
import { describePickupAt } from '../utils/pickupTime';
import styles from './OrderTrackingPage.module.css';

const MAX_ROUNDS = 5; // services/dispatch.py MAX_ROUNDS bilan mos
const POLL_INTERVAL_MS = 5000;
// Haydovchi biriktirilgan (ACCEPTED/IN_PROGRESS): nuqtalar va status o'zgarishi kuzatiladi.
const ACTIVE_POLL_INTERVAL_MS = 10_000;
const ETA_POLL_INTERVAL_MS = 30_000;
// Qidiruv boshlanishini kutayotgan buyurtma uchun (holat soatlab o'zgarmaydi)
const SCHEDULED_POLL_INTERVAL_MS = 60_000;


/** ISO vaqtdan faqat soat:daqiqa (bosqichlar ro'yxati uchun). */
export function OrderTrackingPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const navigate = useNavigate();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [bumping, setBumping] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  // Bekor qilish qaytarib bo'lmaydigan amal — tugma bosilganda o'sha joyning o'zida
  // tasdiq so'raladi (Telegram WebApp'da `window.confirm` ishonchli emas).
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Narx oshirish tugmalari — qiymatlarni backend beradi (bot bilan bir xil ro'yxat)
  const [priceOptions, setPriceOptions] = useState<QuickPriceOption[]>([]);
  // Tahrirlash va narx belgilash — ikkalasi ham faqat haydovchi biriktirilmaguncha ochiq.
  const [editingOrder, setEditingOrder] = useState(false);
  const [editingPrice, setEditingPrice] = useState(false);
  // Qidiruvni to'xtatish/davom ettirish so'rovi ketayotgan payt — ikkala tugma ham
  // bloklanadi, aks holda takroriy bosishda 409 chiqardi.
  const [dispatchBusy, setDispatchBusy] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    if (!orderId) return;
    try {
      const data = await getOrder(Number(orderId));
      setOrder(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Buyurtma topilmadi");
    }
  }, [orderId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Qidiruvni to'xtatish yoki davom ettirish. Javob to'liq buyurtma bo'lib qaytadi,
   *  shuning uchun qayta so'rov (`load`) kerak emas. */
  const changeDispatch = useCallback(
    async (action: 'pause' | 'resume') => {
      if (!orderId || dispatchBusy) return;
      setDispatchBusy(true);
      setError(null);
      try {
        const updated =
          action === 'pause'
            ? await pauseDispatch(Number(orderId))
            : await resumeDispatch(Number(orderId));
        setOrder(updated);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Amal bajarilmadi, qayta urinib ko'ring");
      } finally {
        setDispatchBusy(false);
      }
    },
    [orderId, dispatchBusy],
  );

  useEffect(() => {
    if (!order || FINAL_ORDER_STATUSES.has(order.status)) {
      if (timerRef.current) clearTimeout(timerRef.current);
      return;
    }
    // Ilgari so'rov faqat PENDING'da ishlardi: haydovchi qabul qilgach sahifa "qotib"
    // qolar, yuk olingani/yo'lga chiqqani/yetkazilgani qayta yuklamaguncha ko'rinmasdi.
    let interval: number;
    if (order.status === 'PENDING') {
      // Qidiruv hali boshlanmagan yoki to'xtatilgan bo'lsa — holat o'z-o'zidan o'zgarmaydi.
      const idle = order.dispatch_starts_at != null || order.dispatch_paused_at != null;
      interval = idle ? SCHEDULED_POLL_INTERVAL_MS : POLL_INTERVAL_MS;
    } else if (order.status === 'SCHEDULED') {
      interval = SCHEDULED_POLL_INTERVAL_MS;
    } else {
      interval = ACTIVE_POLL_INTERVAL_MS;
    }
    timerRef.current = setTimeout(load, interval);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [order, load]);

  // Ilova fondan qaytganda (Telegram yopilib-ochilganda) darhol yangilanadi.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [load]);

  // Taklif tushgach variantlarni backend'dan olamiz. Narxni frontend HISOBLAMAYDI:
  // aks holda web va bot turli summalarni ko'rsatardi va chegara tekshiruvi
  // (services/pricing.py) ikki joyda takrorlanardi.
  const bumpOffered = Boolean(order?.price_bump_requested_at) && order?.driver_id == null;
  // Effekt butun `order` obyektiga bog'lanmasin: u har so'rovda yangi havola bo'ladi
  // va variantlar keraksiz qayta yuklanardi. Faqat shu ikki maydon muhim.
  const orderIdForOptions = order?.id ?? null;
  const orderPrice = order?.price ?? null;
  useEffect(() => {
    if (orderIdForOptions == null || !bumpOffered) {
      setPriceOptions([]);
      return;
    }
    let cancelled = false;
    void getPriceOptions(orderIdForOptions)
      .then((data) => {
        if (!cancelled) setPriceOptions(data.quick_price_options);
      })
      .catch(() => {
        if (!cancelled) setPriceOptions([]);
      });
    return () => {
      cancelled = true;
    };
    // `orderPrice` — bump'dan keyin variantlar yangi narxdan qayta hisoblanishi uchun
  }, [orderIdForOptions, orderPrice, bumpOffered]);

  async function handleBump(newPrice: number) {
    if (!order) return;
    setBumping(true);
    setError(null);
    try {
      const updated = await bumpPrice(order.id, newPrice);
      setOrder(updated);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Narxni oshirib bo'lmadi");
    } finally {
      setBumping(false);
    }
  }

  async function handleCancel() {
    if (!order) return;
    setCancelling(true);
    setError(null);
    try {
      await cancelOrder(order.id);
      setConfirmingCancel(false);
      // Javob 204 (tanasi yo'q) — yangilangan holatni qayta o'qiymiz. Status
      // `CANCELLED` bo'lgach so'rovlar (polling) `useEffect` ichida o'zi to'xtaydi.
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Buyurtmani bekor qilib bo'lmadi");
    } finally {
      setCancelling(false);
    }
  }

  // Haydovchi biriktirilgan va yo'lda bo'lsa — jonli joylashuvi kuzatiladi
  // (order/router.py `WS /orders/{id}/ws/driver-location`). Hook har renderda
  // bir xil tartibda chaqirilishi shart, shuning uchun quyidagi `if (!order)`
  // ERTA return'idan OLDIN turadi — `order` hali `null` bo'lsa `enabled=false`.
  const isFound =
    order != null &&
    (order.status === 'SCHEDULED' || order.status === 'ACCEPTED' || order.status === 'IN_PROGRESS');
  const isTrackable = isFound && order?.driver_id != null;
  const driverPoint = useOrderDriverLocation(order?.id ?? null, isTrackable);

  // ETA va joylashuv yangiligi — faqat haydovchi yo'lga chiqqan holatlarda (30 s da bir).
  // "Start" bosilmaguncha haydovchi hali yo'lga chiqmagan — ETA va "joylashuv eskirgan"
  // ogohlantirishi chalg'itardi (masalan yuk 2 kundan keyin ortiladi).
  const etaEnabled =
    order != null &&
    order.driver_id != null &&
    (order.status === 'IN_PROGRESS' || (order.status === 'ACCEPTED' && Boolean(order.started_at)));
  const etaOrderId = order?.id ?? null;
  const [eta, setEta] = useState<OrderEta | null>(null);
  useEffect(() => {
    if (!etaEnabled || etaOrderId == null) {
      setEta(null);
      return;
    }
    let cancelled = false;
    const fetchEta = () =>
      getOrderEta(etaOrderId)
        .then((data) => !cancelled && setEta(data))
        .catch(() => undefined); // ETA ikkinchi darajali — xato bo'lsa jim qoladi
    void fetchEta();
    const timer = window.setInterval(fetchEta, ETA_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // Status o'zgarsa (ACCEPTED -> IN_PROGRESS) maqsad nuqta ham o'zgaradi.
  }, [etaEnabled, etaOrderId, order?.status]);

  if (!order) {
    return (
      <div className={styles.page}>
        <div className={styles.topBar}>
          <button className={styles.backBtn} onClick={() => navigate('/')}>
            <BackIcon />
          </button>
          <span className={styles.title}>Buyurtma</span>
        </div>
        {error && (
          <div className={styles.section}>
            <div className={styles.errorText}>{error}</div>
          </div>
        )}
      </div>
    );
  }

  const isSearching = order.status === 'PENDING';
  const awaitingBump = bumpOffered;
  // Backend hisoblab beradi (`order/schemas.py dispatch_starts_at`) — lead vaqti
  // sozlamasi frontendda takrorlanmasin.
  const scheduledStart = order.dispatch_starts_at ? new Date(order.dispatch_starts_at) : null;
  // Haydovchi biriktirilmagan bo'lsa mijoz buyurtmadan voz kecha oladi. Backend ham
  // shu shartni qo'llaydi (`DELETE /orders/{id}` IN_PROGRESS da 422 qaytaradi).
  const canCancel = order.status === 'PENDING' && order.driver_id == null;
  // Haydovchi biriktirilgach yuk ma'lumotini ham, narxni ham o'zgartirib bo'lmaydi —
  // kelishuv allaqachon tuzilgan. Backend ham aynan shu shartni qo'llaydi.
  const canEdit =
    (order.status === 'PENDING' || order.status === 'SCHEDULED') && order.driver_id == null;
  const dispatchPaused = order.dispatch_paused_at != null;
  // Narx faqat qidiruv HAQIQATAN to'xtagan paytda o'zgaradi. Shart backenddagi
  // `dispatch.ensure_price_editable` bilan bir xil bo'lishi shart — aks holda tugma
  // ochiq ko'rinib, so'rov 409 bilan qaytardi (ilgari `canEdit` `SCHEDULED` ga ruxsat
  // berardi, backend esa faqat `PENDING` ni qabul qilardi — o'sha nomuvofiqlik ham
  // shu yerda tugatildi).
  const canEditPrice =
    order.status === 'PENDING' &&
    order.driver_id == null &&
    (dispatchPaused || awaitingBump || scheduledStart != null);
  // Qidiruv ketmoqda: to'xtatish tugmasi shu holatda ko'rinadi.
  const canPauseDispatch =
    order.status === 'PENDING' &&
    order.driver_id == null &&
    !dispatchPaused &&
    !awaitingBump &&
    scheduledStart == null;
  const progressPercent = Math.min(100, (order.dispatch_round / MAX_ROUNDS) * 100);
  const driverLocation = driverPoint
    ? { latitude: driverPoint.latitude, longitude: driverPoint.longitude }
    : null;
  const originPoint =
    order.origin?.latitude != null && order.origin.longitude != null
      ? { latitude: order.origin.latitude, longitude: order.origin.longitude }
      : null;
  const destinationPoint =
    order.destination?.latitude != null && order.destination.longitude != null
      ? { latitude: order.destination.latitude, longitude: order.destination.longitude }
      : null;
  // Kamida bitta koordinata bo'lsa xarita chizishga arziydi (haydovchi hali
  // biriktirilmagan bo'lsa ham marshrut ko'rinib turadi).
  const hasRoutePoints = originPoint != null || destinationPoint != null;

  return (
    <div className={styles.page}>
      {/* Xarita — sahifaning foni. Marshrut koordinatalari bo'lsa doim ko'rsatiladi
          (ilgari faqat haydovchi biriktirilganda chizilardi), haydovchi nuqtasi esa
          kuzatuv mumkin bo'lganda qo'shiladi. */}
      <div className={styles.mapLayer}>
        {hasRoutePoints ? (
          <YandexMap
            origin={originPoint}
            destination={destinationPoint}
            driverLocation={driverLocation}
            driverStale={eta?.location_stale ?? false}
          />
        ) : (
          <div className={styles.mapPlaceholder}>Marshrut xaritasi mavjud emas</div>
        )}
      </div>

      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate('/')}>
          <BackIcon />
        </button>
        <span className={styles.title}>Buyurtma #{order.id}</span>
      </div>

      <BottomSheet
        initialSnap={isTrackable ? 'peek' : 'half'}
        header={
          <>
            <span className={styles.sheetTitle}>{orderStatusMeta(order.status).label}</span>
            <span className={styles.sheetPrice}>
              {formatPrice(order.price)} {order.currency}
            </span>
          </>
        }
      >
      {/* Har qanday amal xatosi (bekor qilish, to'xtatish, narx) shu yerda ko'rinadi —
          ilgari faqat narx oshirish oynasi ichida chiqardi, qolganlari jim yo'qolardi. */}
      {error && (
        <div className={styles.section} role="alert">
          <div className={styles.errorText}>{error}</div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.statusCard}>
          <OrderStatusBadge status={order.status} />
          <div className={styles.statusHeadline}>
            {/* Qidiruv kutilayotgan (PENDING + dispatch_starts_at) holat SCHEDULED dan
                farqli: SCHEDULED da haydovchi allaqachon bor, bu yerda esa hali yo'q. */}
            {scheduledStart
              ? `Haydovchi qidiruvi ${describePickupAt(scheduledStart)} da boshlanadi`
              : awaitingBump
                ? 'Hozircha haydovchi topilmadi'
                : dispatchPaused
                  ? "Qidiruv to'xtatilgan"
                  : order.status === 'CANCELLED' && order.cancel_reason
                    ? `Bekor qilindi: ${order.cancel_reason}`
                    : (order.status === 'ACCEPTED' || order.status === 'SCHEDULED') && !order.started_at
                      ? order.departure_at
                        ? `Haydovchi ${describePickupAt(new Date(order.departure_at))} da yo'lga chiqadi`
                        : "Haydovchi yo'lga chiqishga tayyorlanmoqda"
                      : orderStatusMeta(order.status).hint}
          </div>

          {eta && <EtaLine eta={eta} />}

          {/* Kelajakka rejalashtirilgan yuk: qidiruv hali boshlanmagan. Progress
              ko'rsatkichi bu yerda chalg'ituvchi bo'lardi ("0/5 haydovchi javob
              kutilmoqda" — aslida hech kimga yuborilmagan). */}
          {scheduledStart && (
            <div className={styles.scheduledNote}>
              Yuk {describePickupAt(new Date(order.pickup_at))} ga rejalashtirilgan.
            </div>
          )}

          {isSearching && !awaitingBump && !scheduledStart && (
            <>
              <div className={styles.progressTrack}>
                <div className={styles.progressFill} style={{ width: `${progressPercent}%` }} />
              </div>
              <div className={styles.progressHint}>
                {order.dispatch_round}/{MAX_ROUNDS} haydovchidan javob kutilmoqda
              </div>
            </>
          )}

          {/* Voz kechish yo'li butun qidiruv davomida ochiq: mijoz "haydovchi topilmadi"
              xabarini kutib o'tirmasdan ham buyurtmadan qaytishi mumkin. Haydovchi
              biriktirilgach tugma yo'qoladi (kelishilgan ishni bir tomonlama bekor
              qilish — alohida masala, backend uni IN_PROGRESS da taqiqlaydi). */}
          {canEdit && (
            <div className={styles.editRow}>
              <button className={styles.editBtn} onClick={() => setEditingOrder(true)}>
                Buyurtmani tahrirlash
              </button>
              <button
                className={styles.editBtn}
                disabled={!canEditPrice}
                onClick={() => setEditingPrice(true)}
              >
                Narxni belgilash
              </button>
            </div>
          )}

          {/* Tugma nega o'chiq ekani darhol tushuntiriladi — aks holda foydalanuvchi
              buzuq deb o'ylardi. */}
          {canEdit && !canEditPrice && (
            <div className={styles.dispatchNote}>
              Hozir haydovchilarga taklif yuborilmoqda. Narxni o'zgartirish uchun avval
              qidiruvni to'xtating yoki taymer tugashini kuting.
            </div>
          )}

          {dispatchPaused && (
            <div className={styles.pausedNote}>
              Qidiruv to'xtatilgan. Endi narxni o'zgartirishingiz mumkin — tayyor
              bo'lgach qidiruvni davom ettiring.
            </div>
          )}

          {canPauseDispatch && (
            <button
              className={styles.dispatchBtn}
              disabled={dispatchBusy}
              onClick={() => void changeDispatch('pause')}
            >
              {dispatchBusy ? 'To’xtatilmoqda...' : 'Qidiruvni to’xtatish'}
            </button>
          )}

          {dispatchPaused && (
            <button
              className={styles.dispatchBtn}
              disabled={dispatchBusy}
              onClick={() => void changeDispatch('resume')}
            >
              {dispatchBusy ? 'Davom ettirilmoqda...' : 'Qidiruvni davom ettirish'}
            </button>
          )}

          {canCancel && !confirmingCancel && (
            <button
              className={styles.cancelBtn}
              disabled={cancelling}
              onClick={() => setConfirmingCancel(true)}
            >
              Buyurtmani bekor qilish
            </button>
          )}
          {canCancel && confirmingCancel && (
            <div className={styles.cancelConfirm}>
              <div className={styles.cancelConfirmText}>Buyurtma bekor qilinsinmi?</div>
              <div className={styles.cancelConfirmActions}>
                <button
                  className={styles.cancelConfirmBtn}
                  disabled={cancelling}
                  onClick={handleCancel}
                >
                  {cancelling ? 'Bekor qilinmoqda...' : 'Ha, bekor qilinsin'}
                </button>
                <button
                  className={styles.cancelBackBtn}
                  disabled={cancelling}
                  onClick={() => setConfirmingCancel(false)}
                >
                  Yo'q
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {isTrackable && !driverLocation && (
        <div className={styles.section}>
          <div className={styles.mapHint}>Haydovchining jonli joylashuvi kutilmoqda...</div>
        </div>
      )}

      {/* ── Haydovchi va aloqa ────────────────────────────────────────────────
          Telefon `tel:` bilan qo'ng'iroqni, `telegram_url` esa suhbatni ochadi
          (backend `https://t.me/{username}` shaklida tayyorlab beradi —
          `order/schemas.py OrderDetailResponse.from_order`). */}
      {order.driver_contact && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Haydovchi</div>
          <div className={styles.driverCard}>
            <div className={styles.contactInfo}>
              <div className={styles.contactName}>{order.driver_contact.full_name}</div>
              <div className={styles.contactMeta}>
                <StarIcon size={13} />
                {Number(order.driver_contact.rating).toFixed(1)}
                {order.driver_contact.truck_type_name && ` · ${order.driver_contact.truck_type_name}`}
                {` · ${order.driver_contact.truck_number}`}
              </div>
            </div>

            <div className={styles.contactLinks}>
              {order.driver_contact.phone_number && (
                <a className={styles.contactLink} href={`tel:${order.driver_contact.phone_number}`}>
                  <PhoneIcon />
                  <span className={styles.contactLinkText}>
                    {order.driver_contact.phone_number}
                  </span>
                </a>
              )}
              {order.driver_contact.telegram_url && (
                <a
                  className={styles.contactLink}
                  href={order.driver_contact.telegram_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  <SendIcon />
                  <span className={styles.contactLinkText}>
                    @{order.driver_contact.username}
                  </span>
                </a>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Yo'l statuslari ──────────────────────────────────────────────────
          Har bir nuqta va uning holati. Haydovchi qadamlarni belgilagan sari
          (`PATCH /orders/{id}/waypoints/{wp}`) bu ro'yxat yangilanadi. */}
      {order.waypoints.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionTitle}>Yo'l bosqichlari</div>
          <ol className={styles.timeline}>
            {order.waypoints.map((wp) => {
              const done = wp.status === 'COMPLETED';
              const skipped = wp.status === 'SKIPPED';
              const active = wp.id === order.current_waypoint?.id;
              return (
                <li
                  key={wp.id}
                  className={`${styles.timelineItem} ${active ? styles.timelineActive : ''}`}
                >
                  <span
                    className={`${styles.timelineDot} ${
                      done ? styles.timelineDotDone : skipped ? styles.timelineDotSkipped : ''
                    }`}
                  />
                  <div className={styles.timelineBody}>
                    <div className={styles.timelineHead}>
                      <span className={styles.timelineType}>{WAYPOINT_TYPE_LABEL[wp.type]}</span>
                      <span className={styles.timelineStatus}>
                        {WAYPOINT_STATUS_LABEL[wp.status]}
                      </span>
                    </div>
                    <div className={styles.timelineAddress}>{shortAddress(wp.address) || 'Manzil ko‘rsatilmagan'}</div>
                    {(wp.arrived_at || wp.completed_at) && (
                      <div className={styles.timelineTime}>
                        {wp.arrived_at && `Yetib keldi: ${formatClock(wp.arrived_at)}`}
                        {wp.arrived_at && wp.completed_at && ' · '}
                        {wp.completed_at && `Yakunlandi: ${formatClock(wp.completed_at)}`}
                      </div>
                    )}
                    {wp.contact_name && (
                      <div className={styles.timelineContact}>
                        {wp.contact_name}
                        {wp.contact_phone && (
                          <a className={styles.timelinePhone} href={`tel:${wp.contact_phone}`}>
                            {wp.contact_phone}
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Buyurtma holati</div>
        <div className={styles.card}>
          <OrderStepper order={order} />
        </div>
      </div>

      {awaitingBump && (
        <div className={styles.section}>
          <div className={styles.bumpBox}>
            <div className={styles.bumpText}>
              {order.dispatch_round > 0
                ? `${order.dispatch_round} ta haydovchidan hech biri javob bermadi.`
                : 'Hozircha mos haydovchi topilmadi.'}{' '}
              Narxni oshirib qidiruvni davom ettiramizmi?
            </div>
            <div className={styles.bumpButtons}>
              {priceOptions.map((option) => (
                <button
                  key={option.increment}
                  className={styles.bumpBtn}
                  disabled={bumping}
                  onClick={() => handleBump(option.price)}
                >
                  +{formatPrice(option.increment)} ({formatPrice(option.price)})
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className={styles.section}>
        <div className={styles.sectionTitle}>Buyurtma ma'lumotlari</div>
        <div className={styles.card}>
          <div className={styles.routeRow}>
            <div className={styles.routePoint}>
              <span className={styles.routeDotOrigin} />
              <span>{shortAddress(order.origin?.address) || routeLabel(null, null)}</span>
            </div>
            <div className={styles.routePoint}>
              <span className={styles.routeDotDest} />
              <span>{shortAddress(order.destination?.address) || '?'}</span>
            </div>
          </div>

          <dl className={styles.detailList}>
            <div className={styles.detailRow}>
              <dt>Yuk</dt>
              <dd>{order.cargo_name}</dd>
            </div>
            <div className={styles.detailRow}>
              <dt>Og'irligi</dt>
              <dd>
                {order.weight} t{order.volume ? ` · ${order.volume} m³` : ''}
              </dd>
            </div>
            {order.total_distance_km != null && (
              <div className={styles.detailRow}>
                <dt>Masofa</dt>
                <dd>{Math.round(order.total_distance_km)} km</dd>
              </div>
            )}
            <div className={styles.detailRow}>
              <dt>Yuklash vaqti</dt>
              <dd>{formatShortDateTime(order.pickup_at)}</dd>
            </div>
            {unloadingLabel(order.unloading_mode, order.unloading_wait_hours) && (
              <div className={styles.detailRow}>
                <dt>Tushirish</dt>
                <dd>{unloadingLabel(order.unloading_mode, order.unloading_wait_hours)}</dd>
              </div>
            )}
            {order.original_price != null && order.original_price !== order.price && (
              <div className={styles.detailRow}>
                <dt>Dastlabki narx</dt>
                <dd className={styles.detailMuted}>
                  {formatPrice(order.original_price)} {order.currency}
                </dd>
              </div>
            )}
            <div className={styles.detailRow}>
              <dt>Narx</dt>
              <dd className={styles.priceValue}>
                {formatPrice(order.price)} {order.currency}
              </dd>
            </div>
          </dl>

          {order.overload_warning && <div className={styles.errorText}>{order.overload_warning}</div>}

          {/* Shu buyurtma bo'yicha yordam so'rash — murojaat support mikroservisida
              ochiladi va buyurtma raqami bog'lanadi. Shundan keyin buyurtma holati
              o'zgarganda ticketga avtomatik yozuv tushib turadi. */}
          <button
            className={styles.supportBtn}
            onClick={() => navigate('/messages', { state: { newTicketForOrderId: order.id } })}
          >
            Muammo bormi? Yordam so'rash
          </button>
        </div>
      </div>
      </BottomSheet>

      {editingOrder && (
        <OrderEditSheet
          order={order}
          onClose={() => setEditingOrder(false)}
          onSaved={(updated) => {
            setOrder(updated);
            setEditingOrder(false);
          }}
        />
      )}

      {editingPrice && (
        <CustomPriceSheet
          order={order}
          onClose={() => setEditingPrice(false)}
          onSaved={(updated) => {
            setOrder(updated);
            setEditingPrice(false);
          }}
        />
      )}
    </div>
  );
}

/** Haydovchi qachon yetib kelishi va joylashuvi qanchalik yangi — status kartasida. */
function EtaLine({ eta }: { eta: OrderEta }) {
  if (eta.gps_lost_reason || eta.location_stale) {
    const minutes = eta.location_age_sec != null ? Math.max(1, Math.round(eta.location_age_sec / 60)) : null;
    return (
      <div className={styles.etaStale} role="status">
        {eta.gps_lost_reason
          ? "Haydovchining joylashuvi o'chgan. U bilan bog'laning yoki biroz kuting."
          : minutes != null
            ? `Haydovchi joylashuvi ${minutes} daqiqa oldin yangilangan`
            : "Haydovchi joylashuvi hali ma'lum emas"}
      </div>
    );
  }
  if (eta.duration_min == null) return null;
  const target = eta.target_type === 'DELIVERY' ? 'Yetkazish manzilig' : 'Yuk olish joyig';
  return (
    <div className={styles.etaLine}>
      {target}a ~{eta.duration_min} daqiqa
      {eta.distance_km != null && ` · ${eta.distance_km} km`}
      <span className={styles.etaClock}> · taxminan {formatEta(eta.duration_min)} da</span>
    </div>
  );
}
