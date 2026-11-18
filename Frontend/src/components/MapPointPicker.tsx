import { useEffect, useRef, useState } from 'react';
import { reverseGeocode } from '../api/orders';
import { getTelegramWebApp } from '../telegram';
import {
  UZBEKISTAN_CENTER,
  UZBEKISTAN_DEFAULT_ZOOM,
  loadYandexMaps,
  type YMap,
  type YMapEvent,
} from '../utils/yandexMaps';
import { BackIcon, LocationIcon } from './icons';
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
export function MapPointPicker({ title, initial, myLocation, tone = 'origin', onConfirm, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<YMap | null>(null);
  const [center, setCenter] = useState<[number, number] | null>(
    initial ? [initial.latitude, initial.longitude] : null,
  );
  const [moving, setMoving] = useState(false);
  const [address, setAddress] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);
  const seqRef = useRef(0);

  // 1) Xarita: bir marta yaratiladi.
  useEffect(() => {
    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;
    loadYandexMaps()
      .then((ymaps) => {
        if (cancelled || !containerRef.current) return;
        const start = initial ?? myLocation;
        const map = new ymaps.Map(
          containerRef.current,
          {
            center: start ? [start.latitude, start.longitude] : UZBEKISTAN_CENTER,
            zoom: start ? POINT_ZOOM : UZBEKISTAN_DEFAULT_ZOOM,
            controls: ['zoomControl', 'trafficControl'],
          },
          { suppressMapOpenBlock: true },
        );
        mapRef.current = map;
        setCenter(map.getCenter());

        map.events.add('actionbegin', () => {
          setMoving(true);
        });
        map.events.add('actionend', () => {
          setMoving(false);
          setCenter(map.getCenter());
          haptic('light');
        });
        // Bir marta bosish — o'sha joy markazga keladi (sudrash shart emas).
        map.events.add('click', (e: YMapEvent) => {
          map.panTo(e.get('coords'), { duration: 250 });
        });

        resizeObserver = new ResizeObserver(() => map.container.fitToViewport());
        resizeObserver.observe(containerRef.current);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      mapRef.current?.destroy();
      mapRef.current = null;
    };
    // Faqat ochilganda — keyingi `initial` o'zgarishi xaritani qayta yaratmasin.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2) Markaz o'zgarganda manzilni aniqlash (oxirgi so'rov natijasigina olinadi).
  useEffect(() => {
    if (!center || moving) return;
    const seq = ++seqRef.current;
    setResolving(true);
    const timer = window.setTimeout(() => {
      reverseGeocode(center[0], center[1])
        .then((res) => seq === seqRef.current && setAddress(res.address ?? 'Xaritada belgilangan nuqta'))
        .catch(() => seq === seqRef.current && setAddress('Xaritada belgilangan nuqta'))
        .finally(() => seq === seqRef.current && setResolving(false));
    }, GEOCODE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [center, moving]);

  function goToMyLocation() {
    const focus = (lat: number, lon: number) =>
      mapRef.current?.setCenter([lat, lon], POINT_ZOOM, { duration: 300 });
    if (myLocation) {
      focus(myLocation.latitude, myLocation.longitude);
    } else if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => focus(pos.coords.latitude, pos.coords.longitude),
        undefined,
        { enableHighAccuracy: true, timeout: 8000 },
      );
    }
  }

  function confirm() {
    if (!center || !address || resolving || moving) return;
    haptic('medium');
    onConfirm({ address, latitude: center[0], longitude: center[1] });
  }

  const busy = moving || resolving || !address;

  return (
    <div className={styles.overlay} role="dialog" aria-label={title}>
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
        <button className={styles.roundBtn} onClick={onClose} aria-label="Orqaga">
          <BackIcon />
        </button>
        <div className={styles.title}>{title}</div>
      </div>

      <button className={styles.myLocationBtn} onClick={goToMyLocation} aria-label="Mening joylashuvim">
        <LocationIcon />
      </button>

      <div className={styles.sheet}>
        <div className={styles.addressLabel}>{moving ? 'Xaritani suring…' : 'Manzil'}</div>
        <div className={styles.address} aria-live="polite">
          {moving || resolving ? <span className={styles.skeleton} /> : address}
        </div>
        <div className={styles.hint}>Xaritani suring yoki kerakli joyni bir marta bosing</div>
        <button className={styles.confirmBtn} disabled={busy} onClick={confirm}>
          Shu manzilni tanlash
        </button>
      </div>
    </div>
  );
}
