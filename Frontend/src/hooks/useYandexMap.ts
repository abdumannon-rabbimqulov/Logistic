import { useEffect, useRef, useState, type RefObject } from 'react';
import {
  loadYandexMaps,
  UZBEKISTAN_CENTER,
  UZBEKISTAN_DEFAULT_ZOOM,
  type YMap,
  type YMaps,
} from '../utils/yandexMaps';

interface Options {
  /** `ymaps.Map` holati (center, zoom, controls). Berilmaganlar — O'zbekiston, zoomControl. */
  state?: Record<string, unknown>;
  /** `ymaps.Map` opsiyalari (masalan `{ minZoom: 4 }`). */
  options?: Record<string, unknown>;
  /** Xarita yaratilgach bir marta: hodisalar, qo'shimcha sozlamalar. */
  onCreate?: (map: YMap, ymaps: YMaps) => void;
}

interface Result {
  mapRef: RefObject<YMap | null>;
  /** Xarita yaratildi — geoObjects bilan ishlash mumkin. */
  ready: boolean;
  /** Yandex skripti yuklanmadi (kalit, tarmoq). */
  failed: boolean;
}

/**
 * Yandex xaritasini konteynerda BIR MARTA yaratadi va to'g'ri yo'q qiladi.
 *
 * Ilgari 4 ta komponentda (YandexMap, LiveMapPage, DriversMap, MapPointPicker) bir xil
 * kod takrorlanardi: skriptni yuklash → `new ymaps.Map` → ResizeObserver bilan
 * `fitToViewport` (konteyner o'lchami o'zgarganda plitkalar "qotib" qolmasligi uchun)
 * → unmount'da `destroy`. Parametrlar faqat birinchi chaqiruvda o'qiladi.
 */
export function useYandexMap(containerRef: RefObject<HTMLDivElement | null>, opts: Options = {}): Result {
  const mapRef = useRef<YMap | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const optsRef = useRef(opts);

  useEffect(() => {
    let cancelled = false;
    let resizeObserver: ResizeObserver | null = null;
    const { state, options, onCreate } = optsRef.current;

    loadYandexMaps()
      .then((ymaps) => {
        if (cancelled || !containerRef.current) return;
        const map = new ymaps.Map(
          containerRef.current,
          { center: UZBEKISTAN_CENTER, zoom: UZBEKISTAN_DEFAULT_ZOOM, controls: ['zoomControl'], ...state },
          options,
        );
        mapRef.current = map;
        onCreate?.(map, ymaps);
        setReady(true);
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
  }, [containerRef]);

  return { mapRef, ready, failed };
}
