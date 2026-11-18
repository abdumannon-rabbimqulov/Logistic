import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import {
  loadYandexMaps,
  UZBEKISTAN_CENTER,
  UZBEKISTAN_DEFAULT_ZOOM,
  type YMap,
} from '../utils/yandexMaps';
import styles from './YandexMap.module.css';

// Bitta nuqtaga (masalan foydalanuvchi joylashuvi) markazlashganda ishlatiladigan zoom.
// Yandex shkalasi 0–19; ko'cha darajasi ko'rinadi, lekin haddan tashqari yaqin emas.
const SINGLE_POINT_ZOOM = 15;
const MY_LOCATION_ZOOM = 16;
// Eng uzoq (kichik) zoom — foydalanuvchi butun O'zbekistonni ko'ra olishi uchun.
const MIN_ZOOM = 4;

interface MapPoint {
  latitude: number;
  longitude: number;
}

export interface YandexMapHandle {
  /** Xaritani berilgan nuqtaga markazlashtirib yaqinlashtiradi ("mening joylashuvim" tugmasi uchun). */
  focusLocation: (latitude: number, longitude: number) => void;
}

interface Props {
  origin?: MapPoint | null;
  destination?: MapPoint | null;
  /** OSRM marshrut chizig'i: [[latitude, longitude], ...] (backend `route_geometry`). */
  route?: [number, number][] | null;
  /** Foydalanuvchining jonli joylashuvi — ko'k nuqta bilan ko'rsatiladi. */
  userLocation?: MapPoint | null;
  /** Boshqa odam (masalan biriktirilgan haydovchi)ning jonli joylashuvi — `userLocation`dan
   *  farqli rang/hint bilan, sender kuzatuv sahifasida ishlatiladi. */
  driverLocation?: MapPoint | null;
  /** Haydovchi joylashuvi eskirgan (2+ daqiqa yangilanmagan) — marker kulrang chiziladi. */
  driverStale?: boolean;
  /** `userLocation` birinchi marta kelganda xarita o'sha nuqtaga markazlashsin
   *  (bosh sahifadagi xarita uchun; buyurtma sahifalarida marshrut ustuvor). */
  followUser?: boolean;
  /** Berilsa — yuklash nuqtasi belgisini xaritada sudrab ko'chirish mumkin bo'ladi;
   *  qo'yib yuborilganda yangi koordinata shu callback'ga uzatiladi. */
  onOriginMove?: (latitude: number, longitude: number) => void;
  /** `onOriginMove` bilan bir xil, tushirish nuqtasi uchun. */
  onDestinationMove?: (latitude: number, longitude: number) => void;
}

// Yandex `Placemark` ning sudrash uchun kerakli qismi (umumiy tur `unknown` bo'lgani uchun).
interface DraggablePlacemark {
  events: { add(type: string, handler: () => void): void };
  geometry: { getCoordinates(): [number, number] };
}

export const YandexMap = forwardRef<YandexMapHandle, Props>(function YandexMap(
  { origin, destination, route, userLocation, driverLocation, driverStale = false, followUser = false, onOriginMove, onDestinationMove },
  ref,
) {
  // Callback'lar ref'da saqlanadi: ular har render'da yangi funksiya bo'lishi mumkin,
  // effekt bog'liqligiga qo'yilsa esa belgilar har safar qayta chizilib, xarita sakraydi.
  const onOriginMoveRef = useRef(onOriginMove);
  const onDestinationMoveRef = useRef(onDestinationMove);
  onOriginMoveRef.current = onOriginMove;
  onDestinationMoveRef.current = onDestinationMove;
  const originDraggable = Boolean(onOriginMove);
  const destinationDraggable = Boolean(onDestinationMove);
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<YMap | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  // Xarita foydalanuvchi nuqtasiga faqat BIR marta markazlashadi — keyin uni
  // qo'lda surganida har yangi koordinatada sakrab ketmasligi uchun.
  const centeredOnUserRef = useRef(false);

  useImperativeHandle(ref, () => ({
    focusLocation: (latitude, longitude) => {
      mapRef.current?.setCenter([latitude, longitude], MY_LOCATION_ZOOM, { duration: 300 });
    },
  }), []);

  useEffect(() => {
    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;
    loadYandexMaps()
      .then((ymaps) => {
        if (cancelled || !containerRef.current) return;
        const map = new ymaps.Map(
          containerRef.current,
          { center: UZBEKISTAN_CENTER, zoom: UZBEKISTAN_DEFAULT_ZOOM, controls: ['zoomControl'] },
          // restrictMapArea ATAYLAB YO'Q: u viewport'ni O'zbekiston to'rtburchagi ichida
          // ushlab, telefon (vertikal) ekranida butun mamlakat ko'rinishiga to'sqinlik qilardi.
          { minZoom: MIN_ZOOM },
        );
        mapRef.current = map;
        setReady(true);

        // Konteyner ymaps o'lchagan paytdan keyin o'zgarsa (masalan, layout hali
        // to'liq joylashmagan bo'lsa yoki klaviatura/varaqlar ekran balandligini
        // o'zgartirsa), plitkalar eski o'lchamda "qotib" qoladi — fitToViewport shuni tuzatadi.
        resizeObserver = new ResizeObserver(() => map.container.fitToViewport());
        resizeObserver.observe(containerRef.current);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      resizeObserver?.disconnect();
      mapRef.current?.destroy();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;

    let cancelled = false;
    loadYandexMaps().then((ymaps) => {
      if (cancelled) return;
      map.geoObjects.removeAll();

      // Marshrut chizig'i belgilardan oldin qo'shiladi — shunda belgilar chiziq ustida qoladi.
      if (route && route.length >= 2) {
        // Premium ko'rinish uchun ikki qatlam: avval kengroq oq "casing" (marshrut xarita
        // fonidan ajralib tursin), ustidan asosiy yashil chiziq. Uchlari yumaloq (round).
        map.geoObjects.add(
          new ymaps.Polyline(route, {}, {
            strokeColor: '#FFFFFF', strokeWidth: 9, strokeOpacity: 0.9,
            strokeLineCap: 'round', strokeLineJoin: 'round',
          }),
        );
        map.geoObjects.add(
          new ymaps.Polyline(route, {}, {
            strokeColor: '#15803D', strokeWidth: 5, strokeOpacity: 1,
            strokeLineCap: 'round', strokeLineJoin: 'round',
          }),
        );
      }

      // Belgi yaratadi; `moveRef` da callback bo'lsa — sudraladigan qiladi va qo'yib
      // yuborilganda (dragend) yangi koordinatani uzatadi.
      const addPointMark = (
        point: MapPoint,
        options: Record<string, unknown>,
        draggable: boolean,
        hint: string,
        moveRef: { current?: (latitude: number, longitude: number) => void },
      ) => {
        const mark = new ymaps.Placemark(
          [point.latitude, point.longitude],
          draggable ? { hintContent: hint } : {},
          { ...options, draggable },
        );
        if (draggable) {
          const dm = mark as DraggablePlacemark;
          dm.events.add('dragend', () => {
            const [lat, lon] = dm.geometry.getCoordinates();
            moveRef.current?.(lat, lon);
          });
        }
        map.geoObjects.add(mark);
      };

      const points: [number, number][] = [];
      if (origin) {
        points.push([origin.latitude, origin.longitude]);
        addPointMark(
          origin,
          { preset: 'islands#circleIcon', iconColor: '#15803D' },
          originDraggable,
          "Yuklash nuqtasi — surib o'zgartiring",
          onOriginMoveRef,
        );
      }
      if (destination) {
        points.push([destination.latitude, destination.longitude]);
        addPointMark(
          destination,
          { preset: 'islands#dotIcon', iconColor: '#0F1319' },
          destinationDraggable,
          "Tushirish nuqtasi — surib o'zgartiring",
          onDestinationMoveRef,
        );
      }

      // Foydalanuvchi (haydovchi) joylashuvi — ko'k "jonli nuqta". Marshrut belgilaridan
      // ajralib turishi uchun boshqa rang va o'lcham.
      if (userLocation) {
        map.geoObjects.add(
          new ymaps.Placemark(
            [userLocation.latitude, userLocation.longitude],
            { hintContent: 'Sizning joylashuvingiz' },
            { preset: 'islands#circleIcon', iconColor: '#1D4ED8', zIndex: 1000 },
          ),
        );
      }

      // Boshqa odam (biriktirilgan haydovchi)ning jonli joylashuvi — sender kuzatuv
      // sahifasida ishlatiladi. `userLocation`dan alohida rang: ikkalasi bir vaqtda
      // chizilishi mumkin (masalan admin ham o'z joylashuvini, ham haydovchinikini ko'rsa).
      if (driverLocation) {
        points.push([driverLocation.latitude, driverLocation.longitude]);
        map.geoObjects.add(
          new ymaps.Placemark(
            [driverLocation.latitude, driverLocation.longitude],
            { hintContent: driverStale ? 'Haydovchining oxirgi ma’lum joylashuvi' : 'Haydovchi joylashuvi' },
            { preset: 'islands#circleIcon', iconColor: driverStale ? '#9CA3AF' : '#F59E0B', zIndex: 999 },
          ),
        );
      }

      // Marshrut bo'lsa — butun chiziq ko'rinadigan qilib moslanadi (chiziq to'g'ri
      // yo'nalishda emas, egri bo'lgani uchun faqat ikki nuqta bo'yicha moslash yetarli emas).
      const fitPoints = route && route.length >= 2 ? route : points;
      if (fitPoints.length >= 2) {
        map.setBounds(ymaps.util.bounds.fromPoints(fitPoints), { checkZoomRange: true, zoomMargin: 60 });
      } else if (fitPoints.length === 1) {
        map.setCenter(fitPoints[0], SINGLE_POINT_ZOOM);
      } else if (followUser && userLocation && !centeredOnUserRef.current) {
        centeredOnUserRef.current = true;
        map.setCenter([userLocation.latitude, userLocation.longitude], MY_LOCATION_ZOOM, { duration: 300 });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [ready, origin, destination, route, userLocation, driverLocation, driverStale, followUser, originDraggable, destinationDraggable]);

  return (
    <div className={styles.wrap}>
      <div ref={containerRef} className={styles.map} />
      {!ready && !failed && <div className={styles.spinner} aria-label="Xarita yuklanmoqda" />}
      {failed && <div className={styles.error}>Xarita yuklanmadi</div>}
    </div>
  );
});
