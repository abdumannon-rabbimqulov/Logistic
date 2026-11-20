import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { createOrder, estimatePrice, reverseGeocode } from '../api/orders';
import { AddressSearchSheet } from '../components/AddressSearchSheet';
import { MapPointPicker } from '../components/MapPointPicker';
import { type CargoDetails, CargoDetailsSheet } from '../components/CargoDetailsSheet';
import { MapLibreMap, type MapLibreMapHandle } from '../components/MapLibreMap';
import {
  BackIcon,
  CardIcon,
  ClockIcon,
  DestinationFlagIcon,
  LocationIcon,
  PinIcon,
  PlusIcon,
  ProfileIcon,
  RouteIcon,
  SettingsIcon,
  SwapIcon,
  truckIconFor,
} from '../components/icons';
import { ApiError } from '../api/client';
import { staticFileUrl } from '../api/truckTypes';
import { useGeolocation } from '../hooks/useGeolocation';
import type { GeocodeSuggestion, OrderCreateInput, PriceEstimateOption } from '../types/api';
import type { OrderPointPrefill, OrderPrefillState } from '../types/navigation';
import { formatEta, formatPrice } from '../utils/format';
import styles from './OrderPage.module.css';

type PointTarget = 'origin' | 'destination' | null;

export function OrderPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const prefill = (location.state as OrderPrefillState | null) ?? null;
  const geolocation = useGeolocation();
  const mapRef = useRef<MapLibreMapHandle>(null);

  const [origin, setOrigin] = useState<OrderPointPrefill | null>(prefill?.origin ?? null);
  const [destination, setDestination] = useState<OrderPointPrefill | null>(prefill?.destination ?? null);
  const [selectedTruckTypeId, setSelectedTruckTypeId] = useState<number | null>(prefill?.truckTypeId ?? null);
  // Rasmi yuklanmagan transport turlari — ularda rasm o'rniga ikonka chiziladi.
  const [failedImages, setFailedImages] = useState<ReadonlySet<number>>(() => new Set());
  const markImageFailed = (id: number) => setFailedImages((prev) => new Set(prev).add(id));
  const [options, setOptions] = useState<PriceEstimateOption[]>([]);
  const [distanceKm, setDistanceKm] = useState<number | null>(null);
  const [durationMin, setDurationMin] = useState<number | null>(null);
  const [routeGeometry, setRouteGeometry] = useState<[number, number][] | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [estimateError, setEstimateError] = useState<string | null>(null);
  const [estimateRevision, setEstimateRevision] = useState(0);
  // Manzil tanlashning asosiy usuli — markazdagi pin bilan xaritadan nuqta belgilash.
  const [pickerTarget, setPickerTarget] = useState<PointTarget>(null);
  const [addressSearchTarget, setAddressSearchTarget] = useState<PointTarget>(null);
  const [pickerDraft, setPickerDraft] = useState<OrderPointPrefill | null>(null);
  const [cargoSheetOpen, setCargoSheetOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Yuk og'irligi (tonna) — narx og'irlikka ham bog'liq (truck type'ning 1 tonna-km narxi).
  // Kiritish paytida har harfda so'rov ketmasligi uchun 500 ms kechiktiriladi.
  const [cargoWeightInput, setCargoWeightInput] = useState<number | null>(null);
  const [cargoWeight, setCargoWeight] = useState<number | null>(null);
  useEffect(() => {
    document.title = 'Yangi buyurtma · YUK';
  }, []);
  useEffect(() => {
    const id = window.setTimeout(() => setCargoWeight(cargoWeightInput), 500);
    return () => window.clearTimeout(id);
  }, [cargoWeightInput]);

  // Joriy manzilni avtomatik aniqlash (faqat origin hali berilmagan bo'lsa)
  useEffect(() => {
    if (origin || !geolocation.coords) return;
    const { latitude, longitude } = geolocation.coords;
    reverseGeocode(latitude, longitude)
      .then((res) => {
        setOrigin({ address: res.address ?? "Joriy joylashuv", latitude, longitude });
      })
      .catch(() => {
        // aniqlanmasa — foydalanuvchi manzil qatoridan xaritani ochib tanlaydi
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geolocation.coords]);

  // Ikkala manzil ham bo'lganda narx/masofa hisoblanadi
  useEffect(() => {
    if (!origin || !destination) {
      setOptions([]);
      setDistanceKm(null);
      setDurationMin(null);
      setRouteGeometry(null);
      setEstimateError(null);
      return;
    }
    let cancelled = false;
    setEstimating(true);
    setEstimateError(null);
    estimatePrice(
      { latitude: origin.latitude, longitude: origin.longitude },
      { latitude: destination.latitude, longitude: destination.longitude },
      cargoWeight,
    )
      .then((res) => {
        if (cancelled) return;
        setOptions(res.options);
        setDistanceKm(res.distance_km);
        setDurationMin(res.duration_min);
        setRouteGeometry(res.route_geometry?.length ? res.route_geometry : null);
        setSelectedTruckTypeId((prev) => prev ?? res.options[0]?.truck_type_id ?? null);
      })
      .catch((err) => {
        if (cancelled) return;
        setOptions([]);
        setRouteGeometry(null);
        setEstimateError(err instanceof ApiError ? err.message : 'Masofa va narx hisoblanmadi. Qayta urinib ko‘ring.');
      })
      .finally(() => {
        if (!cancelled) setEstimating(false);
      });
    return () => {
      cancelled = true;
    };
  }, [origin, destination, cargoWeight, estimateRevision]);

  function handleSwap() {
    setOrigin(destination);
    setDestination(origin);
  }

  function openPointPicker(target: Exclude<PointTarget, null>) {
    setPickerDraft(null);
    setPickerTarget(target);
  }

  function returnToMapPicker() {
    const target = addressSearchTarget;
    setAddressSearchTarget(null);
    if (target) setPickerTarget(target);
  }

  function handleAddressSelected(suggestion: GeocodeSuggestion) {
    const target = addressSearchTarget;
    if (!target) return;
    setPickerDraft({ address: suggestion.address, latitude: suggestion.latitude, longitude: suggestion.longitude });
    setAddressSearchTarget(null);
    setPickerTarget(target);
  }

  // "Mening joylashuvim" tugmasi — xaritani foydalanuvchi joylashuviga yaqinlashtiradi.
  // Avval useGeolocation aniqlagan koordinata ishlatiladi; hali aniqlanmagan bo'lsa
  // (yoki ruxsat endi berilgan bo'lsa) qaytadan so'raladi.
  function handleMyLocation() {
    const focus = (lat: number, lon: number) => mapRef.current?.focusLocation(lat, lon);
    if (geolocation.coords) {
      focus(geolocation.coords.latitude, geolocation.coords.longitude);
    } else if (origin) {
      focus(origin.latitude, origin.longitude);
    } else if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => focus(pos.coords.latitude, pos.coords.longitude),
        undefined,
        { enableHighAccuracy: true, timeout: 8000 },
      );
    }
  }

  // Xaritada belgi surib qo'yilganda: yangi koordinata uchun manzil nomi aniqlanadi,
  // keyin nuqta BIR marta yangilanadi (narx/marshrut ham bir marta qayta hisoblanadi).
  // Tez-tez surilsa, faqat eng oxirgi surishning natijasi qo'llanadi.
  const moveSeqRef = useRef({ origin: 0, destination: 0 });
  function handlePointMoved(target: 'origin' | 'destination', latitude: number, longitude: number) {
    const seq = ++moveSeqRef.current[target];
    const apply = (address: string) => {
      if (moveSeqRef.current[target] !== seq) return;
      const point: OrderPointPrefill = { address, latitude, longitude };
      if (target === 'origin') setOrigin(point);
      else setDestination(point);
    };
    reverseGeocode(latitude, longitude)
      .then((res) => apply(res.address ?? 'Xaritada belgilangan nuqta'))
      .catch(() => apply('Xaritada belgilangan nuqta'));
  }

  const selectedOption = useMemo(
    () => options.find((o) => o.truck_type_id === selectedTruckTypeId) ?? null,
    [options, selectedTruckTypeId],
  );

  const canSubmit = Boolean(origin && destination && selectedOption && !estimating);

  async function handleCargoSubmit(details: CargoDetails) {
    if (!origin || !destination || !selectedTruckTypeId) return;
    setSubmitting(true);
    setSubmitError(null);
    const payload: OrderCreateInput = {
      cargo_name: details.cargoName,
      weight: details.weight,
      volume: details.volume,
      // Foydalanuvchi tanlagan payt (CargoDetailsSheet). Ilgari bu yerda qattiq
      // `new Date()` turardi — ya'ni buyurtma DOIM "hozir tayyor" bo'lardi va
      // kelajakka rejalashtirish umuman mumkin emas edi.
      pickup_at: details.pickupAt.toISOString(),
      // Tushirish sharti ixtiyoriy — tanlanmagan bo'lsa maydonlar umuman yuborilmaydi.
      unloading_mode: details.unloadingMode,
      unloading_wait_hours: details.unloadingWaitHours,
      required_truck_type_id: selectedTruckTypeId,
      waypoints: [
        { sequence: 1, type: 'PICKUP', address: origin.address, latitude: origin.latitude, longitude: origin.longitude },
        { sequence: 2, type: 'DELIVERY', address: destination.address, latitude: destination.latitude, longitude: destination.longitude },
      ],
    };
    try {
      const order = await createOrder(payload);
      navigate(`/orders/${order.id}`, { replace: true });
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Buyurtma yaratilmadi, qayta urinib ko'ring");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.mapLayer}>
        <MapLibreMap
          ref={mapRef}
          origin={origin}
          destination={destination}
          route={routeGeometry}
          onOriginClick={() => openPointPicker('origin')}
          onDestinationClick={() => openPointPicker('destination')}
          onOriginMove={(lat, lon) => handlePointMoved('origin', lat, lon)}
          onDestinationMove={(lat, lon) => handlePointMoved('destination', lat, lon)}
        />
        {durationMin !== null && (
          <div className={styles.routeBadge}>
            <span className={styles.routeBadgePart}>
              <RouteIcon />
              {distanceKm !== null ? `${Math.round(distanceKm)} km` : '—'}
            </span>
            <span className={styles.routeBadgeSep} />
            <span className={styles.routeBadgePart}>
              <ClockIcon />
              {formatEta(durationMin)}
            </span>
          </div>
        )}
        <button className={styles.myLocationBtn} onClick={handleMyLocation} aria-label="Mening joylashuvim">
          <LocationIcon />
        </button>
      </div>

      <div className={styles.topBar}>
        <button className={styles.iconBtn} onClick={() => navigate('/profile')} aria-label="Profil">
          <ProfileIcon color="var(--color-gray-800)" strokeWidth={1.9} />
        </button>
      </div>
      <div className={styles.topBarSecondary}>
        <button className={styles.iconBtn} onClick={() => navigate(-1)} aria-label="Orqaga">
          <BackIcon />
        </button>
        <button className={styles.iconBtn} onClick={handleSwap} aria-label="Manzillarni almashtirish">
          <SwapIcon />
        </button>
      </div>

      <div className={styles.sheet}>
        <div className={styles.dragHandle} />

        <div className={styles.addressBlock}>
          <button className={styles.addressRow} onClick={() => openPointPicker('origin')}>
            <span className={styles.originDot} />
            <div className={styles.rowText}>
              <div className={styles.rowLabel}>{origin ? "Qayerdan" : "Joriy manzil aniqlanmoqda..."}</div>
              {origin ? (
                <div className={styles.rowValue}>{origin.address}</div>
              ) : (
                <div className={styles.rowValuePlaceholder}>Manzil tanlang</div>
              )}
            </div>
            <span className={styles.mapPill}>
              <PinIcon size={14} />
              Xaritadan
            </span>
          </button>

          <button className={styles.addressRow} onClick={() => openPointPicker('destination')}>
            <DestinationFlagIcon />
            <div className={styles.rowText}>
              <div className={styles.rowLabel}>Qayerga</div>
              {destination ? (
                <div className={styles.rowValue}>
                  {destination.address}
                  {distanceKm !== null ? ` · ${Math.round(distanceKm)} km` : ''}
                </div>
              ) : (
                <div className={styles.rowValuePlaceholder}>Manzil tanlang</div>
              )}
            </div>
            <span className={styles.addBtn}>
              <PlusIcon />
            </span>
          </button>
        </div>

        {options.length > 0 && (
          <>
            <div className={styles.tabsRow} role="group" aria-label="Transport turini tanlang">
              <button
                type="button"
                className={selectedTruckTypeId === null ? styles.tabActive : styles.tab}
                aria-pressed={selectedTruckTypeId === null}
                onClick={() => setSelectedTruckTypeId(null)}
              >Hammasi</button>
              {options.map((opt) => (
                <button
                  type="button"
                  key={opt.truck_type_id}
                  className={opt.truck_type_id === selectedTruckTypeId ? styles.tabActive : styles.tab}
                  aria-pressed={opt.truck_type_id === selectedTruckTypeId}
                  onClick={() => setSelectedTruckTypeId(opt.truck_type_id)}
                >
                  {opt.name}
                </button>
              ))}
            </div>

            <div className={styles.truckRow}>
              {options.map((opt) => {
                const Icon = truckIconFor(opt.name);
                const selected = opt.truck_type_id === selectedTruckTypeId;
                return (
                  <button
                    key={opt.truck_type_id}
                    className={selected ? styles.truckCardSelected : styles.truckCard}
                    onClick={() => setSelectedTruckTypeId(opt.truck_type_id)}
                  >
                    {opt.image_url && !failedImages.has(opt.truck_type_id) ? (
                      <img
                        className={styles.truckImg}
                        src={staticFileUrl(opt.image_url)}
                        alt={opt.name}
                        loading="lazy"
                        onError={() => markImageFailed(opt.truck_type_id)}
                      />
                    ) : (
                      <Icon color={selected ? 'var(--color-accent-pressed)' : 'var(--color-text-secondary)'} />
                    )}
                    {durationMin !== null && (
                      <span className={selected ? styles.truckDurationSelected : styles.truckDuration}>
                        {Math.round(durationMin)} daq
                      </span>
                    )}
                    <span className={selected ? styles.truckNameSelected : styles.truckName}>{opt.name}</span>
                    <span className={selected ? styles.truckPriceSelected : styles.truckPrice}>{formatPrice(opt.price)}</span>
                  </button>
                );
              })}
            </div>
          </>
        )}

        {estimating && <div className={styles.estimateStatus} role="status">Masofa va narx hisoblanmoqda…</div>}
        {estimateError && (
          <div className={styles.estimateError} role="alert">
            <span>{estimateError}</span>
            <button type="button" onClick={() => setEstimateRevision((revision) => revision + 1)}>Qayta hisoblash</button>
          </div>
        )}
        {submitError && <div className={styles.errorBanner}>{submitError}</div>}

        <div className={styles.ctaRow}>
          <span className={styles.ctaSideBtn}>
            <CardIcon />
          </span>
          <button className={styles.ctaMain} disabled={!canSubmit || submitting} onClick={() => setCargoSheetOpen(true)}>
            {selectedOption ? `Buyurtma berish · ${formatPrice(selectedOption.price)}` : 'Buyurtma berish'}
          </button>
          <span className={styles.ctaSideBtn}>
            <SettingsIcon />
          </span>
        </div>
      </div>

      {addressSearchTarget && (
        <AddressSearchSheet
          title={addressSearchTarget === 'origin' ? 'Yuk olish joyini qidirish' : 'Yetkazish manzilini qidirish'}
          onSelect={handleAddressSelected}
          onClose={returnToMapPicker}
          onPickOnMap={returnToMapPicker}
        />
      )}

      {pickerTarget && (
        <MapPointPicker
          title={pickerTarget === 'origin' ? 'Yuk olish joyi' : 'Yetkazish manzili'}
          tone={pickerTarget}
          initial={pickerDraft ?? (pickerTarget === 'origin' ? origin : destination)}
          myLocation={geolocation.coords}
          onSearch={(point) => {
            setPickerDraft(point);
            setAddressSearchTarget(pickerTarget);
            setPickerTarget(null);
          }}
          onClose={() => {
            setPickerTarget(null);
            setPickerDraft(null);
          }}
          onConfirm={(point) => {
            if (pickerTarget === 'origin') setOrigin(point);
            else setDestination(point);
            setPickerTarget(null);
            setPickerDraft(null);
          }}
        />
      )}

      {cargoSheetOpen && (
        <CargoDetailsSheet
          onSubmit={handleCargoSubmit}
          onClose={() => setCargoSheetOpen(false)}
          submitting={submitting}
          apiError={submitError}
          onWeightChange={setCargoWeightInput}
          price={cargoWeight != null ? selectedOption?.price ?? null : null}
          priceLoading={estimating || cargoWeight !== cargoWeightInput}
        />
      )}
    </div>
  );
}
