import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import { reverseGeocode } from '../api/orders';
import { getTelegramWebApp } from '../telegram';
import { UZ_BOUNDS, UZ_CENTER, useMapLibreMap } from '../hooks/useMapLibreMap';
import { BackIcon, LocationIcon, SearchIcon } from './icons';
import styles from './MapPointPicker.module.css';

export interface PickedPoint {
  address: string;
  latitude: number;
  longitude: number;
}

interface Props {
  title: string;
  /** Boshlang'ich nuqta (mavjud manzil). Bo'lmasa — foydalanuvchi joylashuvi yoki O'zbekiston. */
  initial?: { latitude: number; longitude: number } | null;
  /** Foydalanuvchining joriy joylashuvi ("mening joylashuvim" tugmasi uchun). */
  myLocation?: { latitude: number; longitude: number } | null;
  /** Pin rangi: yuk olish — yashil, yetkazish — qizil. */
  tone?: 'origin' | 'destination';
  /** Ixtiyoriy qidiruvga o'tish; qidiruv natijasi nuqtani tasdiqlamaydi. */
  onSearch: (point: PickedPoint) => void;
  onConfirm: (point: PickedPoint) => void;
  onClose: () => void;
}

const POINT_ZOOM = 16;
const GEOCODE_DEBOUNCE_MS = 400;

function haptic(kind: 'light' | 'medium') {
  try {
    getTelegramWebApp()?.HapticFeedback?.impactOccurred(kind);
  } catch {
    // eski klientlarda HapticFeedback yo'q
  }
}

/**
 * Xaritadan nuqta tanlash — Yandex Go uslubida: pin ekran markazida QOTIB turadi,
 * foydalanuvchi esa xaritani uning ostida suradi. Xarita to'xtagach markaz
 * koordinatasi uchun manzil aniqlanadi (debounce bilan).
 *
 * Ilgari nuqtani o'zgartirish uchun kichik belgini aniq bosib sudrash kerak edi —
 * telefon ekranida bu qiyin edi. Endi istalgan joyni surish yoki bir marta bosish
 * kifoya: bosilgan joy markazga keladi.
 */
export function MapPointPicker({ title, initial, myLocation, tone = 'origin', onSearch, onConfirm, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  onCloseRef.current = onClose;
  const [center, setCenter] = useState<[number, number] | null>(
    initial ? [initial.latitude, initial.longitude] : null,
  );
  const [moving, setMoving] = useState(false);
  const [address, setAddress] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const [addressFallback, setAddressFallback] = useState(false);
  const [locationError, setLocationError] = useState<string | null>(null);
  const seqRef = useRef(0);

  // 1) Xarita: bir marta yaratiladi; MapLibre kutubxonasi shu yerda lazy-load bo'ladi.
  const start = initial ?? myLocation;
  const { mapRef: liveMapRef, ready: mapReady, failed: mapFailed } = useMapLibreMap(containerRef, {
    center: start ? [start.longitude, start.latitude] : UZ_CENTER,
    zoom: start ? POINT_ZOOM : 5,
    minZoom: 4,
    maxBounds: UZ_BOUNDS,
  });
  useEffect(() => {
    const map = liveMapRef.current;
    if (!mapReady || !map) return;
    const updateCenter = () => {
      const { lat, lng } = map.getCenter();
      setCenter([lat, lng]);
    };
    const onMoveEnd = () => {
      const { lat, lng } = map.getCenter();
      setCenter([lat, lng]);
      setMoving(false);
      setLocationError(null);
      haptic('light');
    };
    map.on('movestart', () => setMoving(true));
    map.on('moveend', onMoveEnd);
    map.on('click', (event) => map.easeTo({ center: event.lngLat, duration: 250 }));
    updateCenter();
    return () => {
      map.off('moveend', onMoveEnd);
    };
  }, [liveMapRef, mapReady]);

  // 2) Markaz o'zgarganda manzilni aniqlash (oxirgi so'rov natijasigina olinadi).
  useEffect(() => {
    if (!center || moving) return;
    const seq = ++seqRef.current;
    setResolving(true);
    const timer = window.setTimeout(() => {
      reverseGeocode(center[0], center[1])
        .then((res) => {
          if (seq !== seqRef.current) return;
          const resolvedAddress = res.address?.trim();
          setAddress(resolvedAddress || 'Xaritadagi tanlangan nuqta');
          setAddressFallback(!resolvedAddress);
        })
        .catch(() => {
          if (seq !== seqRef.current) return;
          setAddress('Xaritadagi tanlangan nuqta');
          setAddressFallback(true);
        })
        .finally(() => seq === seqRef.current && setResolving(false));
    }, GEOCODE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      if (seqRef.current === seq) seqRef.current += 1;
    };
  }, [center, moving]);

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const frame = requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, []);

  function goToMyLocation() {
    setLocationError(null);
    const focus = (lat: number, lon: number) => {
      liveMapRef.current?.easeTo({ center: [lon, lat], zoom: POINT_ZOOM, duration: 300 });
    };
    if (myLocation) {
      focus(myLocation.latitude, myLocation.longitude);
    } else if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => focus(pos.coords.latitude, pos.coords.longitude),
        (error) => setLocationError(error.code === 1
          ? 'Joylashuvga ruxsat berilmagan. Telefon yoki brauzer sozlamalaridan lokatsiyani yoqing. Yoki xaritadan manzilni qo‘lda tanlang.'
          : error.code === 3
            ? 'Joylashuvni aniqlash vaqti tugadi. GPS va internetni tekshiring yoki xaritadan manzil tanlang.'
            : 'Joylashuv aniqlanmadi. GPS/lokatsiyani yoqing yoki xaritadan manzilni qo‘lda tanlang.'),
        { enableHighAccuracy: true, timeout: 8000 },
      );
    } else {
      setLocationError('Qurilmangiz joylashuvni aniqlashni qo‘llab-quvvatlamaydi. Xaritadan manzilni qo‘lda tanlang.');
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Escape') {
      event.preventDefault();
      onCloseRef.current();
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    )).filter((element) => element.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function confirm() {
    if (!center || !address || resolving || moving) return;
    haptic('medium');
    onConfirm({ address, latitude: center[0], longitude: center[1] });
  }

  const busy = !mapReady || mapFailed || moving || resolving || !address;

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={handleKeyDown}>
      <div ref={containerRef} className={styles.map} />

      {/* Markazdagi pin: xarita surilayotganda yuqoriga ko'tariladi, soya qoladi. */}
      <div className={styles.pinWrap} aria-hidden="true">
        <div className={`${styles.pin} ${tone === 'destination' ? styles.pinDestination : ''} ${moving ? styles.pinLifted : ''}`}>
          <span className={styles.pinHead} />
          <span className={styles.pinStem} />
        </div>
        <span className={`${styles.pinShadow} ${moving ? styles.pinShadowLifted : ''}`} />
      </div>

      <div className={styles.topBar}>
        <button ref={closeButtonRef} type="button" className={styles.roundBtn} onClick={onClose} aria-label="Orqaga">
          <BackIcon />
        </button>
        <h2 className={styles.title} id={titleId}>{title}</h2>
        <button
          type="button"
          className={styles.roundBtn}
          onClick={() => center && onSearch({ address: address ?? 'Xaritadagi tanlangan nuqta', latitude: center[0], longitude: center[1] })}
          disabled={!mapReady || mapFailed || !center}
          aria-label="Manzil qidirish"
          title="Manzil qidirish"
        >
          <SearchIcon size={19} />
        </button>
      </div>

      <button type="button" className={styles.myLocationBtn} onClick={goToMyLocation} disabled={!mapReady || mapFailed} aria-label="Mening joylashuvim" title="Mening joylashuvim">
        <LocationIcon />
      </button>

      <div className={styles.sheet}>
        <div className={styles.addressLabel}>{moving ? 'Xaritani suring…' : 'Manzil'}</div>
        <div className={styles.address} aria-live="polite">
          {moving || resolving ? <span className={styles.skeleton} /> : address}
        </div>
        {mapFailed ? (
          <div className={styles.error} role="alert">Xarita yuklanmadi. Internetni tekshirib, oynani qayta oching.</div>
        ) : locationError ? (
          <div className={styles.error} role="status">{locationError}</div>
        ) : addressFallback ? (
          <div className={styles.hint} role="status">Ko‘cha nomi topilmadi — aniq nuqta koordinata bilan saqlanadi.</div>
        ) : (
          <div className={styles.hint}>Xaritani suring yoki kerakli joyni bir marta bosing</div>
        )}
        <button type="button" className={styles.confirmBtn} disabled={busy} onClick={confirm}>
          Shu manzilni tanlash
        </button>
      </div>

    </div>
  );
}
