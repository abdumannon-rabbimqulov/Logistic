import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useYandexMap } from '../hooks/useYandexMap';
import { getLiveMap } from '../api/orders';
import { staticFileUrl } from '../api/truckTypes';
import { BottomNav } from '../components/BottomNav';
import { DriverBottomNav } from '../components/DriverBottomNav';
import { CloseIcon, LocationIcon, RouteIcon, WeightIcon } from '../components/icons';
import type {
  LiveMapFilter,
  LiveMapItem,
  LiveMapMode,
  LiveMapResponse,
} from '../types/api';
import { formatPrice, shortAddress } from '../utils/format';
import { loadYandexMaps } from '../utils/yandexMaps';
import styles from './LiveMapPage.module.css';

interface Props {
  role: 'sender' | 'driver';
}

const POLL_MS = 10_000;
const STORAGE_KEY = 'liveMapFilter.v1';
const DEFAULT_FILTER: LiveMapFilter = { mode: 'in_transit', fromRegion: null, toRegion: null, truckTypeId: null };

const MODES: { value: LiveMapMode; label: string }[] = [
  { value: 'in_transit', label: "Yo'ldagi yuklar" },
  { value: 'empty', label: "Bo'sh mashinalar" },
  { value: 'all', label: 'Hammasi' },
];

const CARGO_COLOR = '#1D4ED8';
const EMPTY_COLOR = '#16A34A';
const REGION_COLORS = ['#DCEFE7', '#FCE8D9', '#E4EAFB', '#F4E7F5', '#F9F1D4', '#DCEEF4'];
type RegionFeature = { geometry: { type: string; coordinates: unknown }; properties: { name: string } };

// O‘zbekistonni qamrab oluvchi taxminiy koordinata chegaralari.
// Yandex restrictMapArea to‘rtburchak bilan ishlaydi, davlat poligoni emas.
const UZBEKISTAN_BOUNDS: [[number, number], [number, number]] = [[37.1, 55.9], [45.6, 73.2]];
const UZBEKISTAN_CENTER: [number, number] = [41.377491, 64.585262];

function readStoredFilter(): LiveMapFilter {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_FILTER;
    return { ...DEFAULT_FILTER, ...(JSON.parse(raw) as Partial<LiveMapFilter>) };
  } catch {
    return DEFAULT_FILTER;
  }
}

function storeFilter(filter: LiveMapFilter) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filter));
  } catch {
    // Saqlab bo'lmasa (private rejim) — filter faqat shu sessiyada qoladi
  }
}

function tons(value: number | null | undefined): string {
  if (value == null) return '—';
  const n = Number(value);
  return `${Number.isInteger(n) ? n : n.toFixed(1)} t`;
}

function shortRegion(name: string | null | undefined): string {
  if (!name) return '—';
  return name.replace(/ viloyati$/, '').replace(/ Respublikasi$/, '');
}

/**
 * Jonli yuk xaritasi — sender va haydovchi uchun bir xil.
 * Ko'rsatiladi: mashina turi, yuk og'irligi, A → B, masofa, narx.
 * Ko'rsatilMAYDI: haydovchi ismi, davlat raqami, telefon (backend ham qaytarmaydi).
 */
export function LiveMapPage({ role }: Props) {
  const [filter, setFilter] = useState<LiveMapFilter>(readStoredFilter);
  const [data, setData] = useState<LiveMapResponse | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [regionShapes, setRegionShapes] = useState<RegionFeature[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [locationError, setLocationError] = useState<string | null>(null);
  const [locating, setLocating] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const { mapRef, ready: mapReady, failed: mapFailed } = useYandexMap(containerRef, {
    state: { center: UZBEKISTAN_CENTER, zoom: 4 },
    options: { minZoom: 2, restrictMapArea: UZBEKISTAN_BOUNDS },
    onCreate: (map) => {
      map.options.set('yandexMapDisablePoiInteractivity', true);
      // Bo'sh joy bosilsa tanlov yopiladi
      map.events.add('click', () => setSelectedId(null));
    },
  });
  const fittedRef = useRef(false);
  const overviewBoundsRef = useRef<[[number, number], [number, number]]>(UZBEKISTAN_BOUNDS);

  useEffect(() => {
    fetch('/uz_regions.geojson').then((r) => { if (!r.ok) throw new Error('regions'); return r.json(); })
      .then((geo: { features?: RegionFeature[] }) => setRegionShapes(geo.features ?? []))
      .catch(() => setRegionShapes([]));
  }, []);

  const updateFilter = useCallback((patch: Partial<LiveMapFilter>) => {
    setFilter((prev) => {
      const next = { ...prev, ...patch };
      storeFilter(next);
      return next;
    });
    fittedRef.current = true;
    setSelectedId(null);
  }, []);

  // Ma'lumot: filter o'zgarganda darhol, keyin har 10 s (sahifa ko'rinib turganda).
  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function load() {
      try {
        const res = await getLiveMap(filter);
        if (cancelled) return;
        setData(res);
        setLoadError(false);
      } catch {
        if (!cancelled) setLoadError(true);
      }
    }

    function schedule() {
      window.clearTimeout(timer);
      timer = window.setTimeout(async () => {
        if (!document.hidden) await load();
        if (!cancelled) schedule();
      }, POLL_MS);
    }

    function onVisible() {
      if (!document.hidden) load();
    }

    load().then(() => !cancelled && schedule());
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [filter]);

  const items = useMemo(() => data?.items ?? [], [data]);
  const selected = useMemo(() => items.find((i) => i.marker_id === selectedId) ?? null, [items, selectedId]);

  // Markerlar + tanlangan yukning A/B nuqtalari
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map) return;
    let cancelled = false;

    loadYandexMaps().then((ymaps) => {
      if (cancelled) return;
      map.geoObjects.removeAll();
      // Viloyat chegaralari: yengil, yarim shaffof qatlam; markerlar ustida qoladi.
      regionShapes.forEach((feature, index) => {
        const raw = feature.geometry.coordinates as number[][][] | number[][][][];
        const polygons = feature.geometry.type === 'MultiPolygon' ? raw as number[][][][] : [raw as number[][][]];
        for (const polygon of polygons) {
          const rings = polygon.map((ring) => ring.map(([lon, lat]) => [lat, lon] as [number, number]));
          map.geoObjects.add(new ymaps.Polygon(rings, { hintContent: feature.properties.name }, {
            fillColor: REGION_COLORS[index % REGION_COLORS.length], fillOpacity: 0.28,
            strokeColor: '#64748B', strokeWidth: 1.5, strokeOpacity: 0.85,
            interactivityModel: 'default#transparent',
          }));
        }
      });

      for (const item of items) {
        const point: [number, number] = [item.lat, item.lon];
        const isSelected = item.marker_id === selectedId;
        const placemark = new ymaps.Placemark(
          point,
          {
            iconContent: item.has_cargo ? '🚚' : '🚛',
            hintContent: [item.truck_type_name, item.has_cargo ? tons(item.weight) : "bo'sh"]
              .filter(Boolean)
              .join(' · '),
          },
          {
            preset: 'islands#blueCircleIcon',
            iconColor: item.has_cargo ? (isSelected ? '#0F1319' : CARGO_COLOR) : EMPTY_COLOR,
            zIndex: isSelected ? 1000 : 100,
          },
        ) as { events: { add(type: string, cb: (e: { stopPropagation?: () => void }) => void): void } };
        placemark.events.add('click', (event) => { event.stopPropagation?.(); setSelectedId(item.marker_id); });
        map.geoObjects.add(placemark);
      }

      const sel = items.find((i) => i.marker_id === selectedId);
      if (sel?.has_cargo && sel.pickup_lat != null && sel.pickup_lon != null && sel.delivery_lat != null && sel.delivery_lon != null) {
        const a: [number, number] = [sel.pickup_lat, sel.pickup_lon];
        const b: [number, number] = [sel.delivery_lat, sel.delivery_lon];
        map.geoObjects.add(
          new ymaps.Polyline([a, [sel.lat, sel.lon], b], {}, {
            strokeColor: CARGO_COLOR,
            strokeWidth: 3,
            strokeOpacity: 0.7,
            strokeStyle: 'shortdash',
          }),
        );
        map.geoObjects.add(new ymaps.Placemark(a, { iconContent: 'A' }, { preset: 'islands#greenIcon' }));
        map.geoObjects.add(new ymaps.Placemark(b, { iconContent: 'B' }, { preset: 'islands#redIcon' }));
      }


    });

    return () => {
      cancelled = true;
    };
  }, [mapReady, mapRef, items, selectedId, regionShapes]);

  // Mamlakatning barcha chegaralarini birinchi yuklanishda ekranga sig'dirish.
  useEffect(() => {
    if (!mapReady || !mapRef.current || !regionShapes.length || fittedRef.current) return;
    const coords: [number, number][] = [];
    for (const feature of regionShapes) {
      const raw = feature.geometry.coordinates as number[][][] | number[][][][];
      const polygons = feature.geometry.type === 'MultiPolygon' ? raw as number[][][][] : [raw as number[][][]];
      for (const polygon of polygons) for (const ring of polygon)
        for (const [lon, lat] of ring) coords.push([lat, lon]);
    }
    if (!coords.length) return;
    let minLat = 90, minLon = 180, maxLat = -90, maxLon = -180;
    for (const [lat, lon] of coords) {
      minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
      minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
    }
    overviewBoundsRef.current = [[minLat, minLon], [maxLat, maxLon]];
    fittedRef.current = true;
    mapRef.current.setBounds(overviewBoundsRef.current, { checkZoomRange: true, zoomMargin: [24, 20, 24, 20] });
  }, [mapReady, mapRef, regionShapes]);

  // Tanlangan yuk to'liq ko'rinsin: A, mashina, B
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !selected) return;
    loadYandexMaps().then((ymaps) => {
      const pts: [number, number][] = [[selected.lat, selected.lon]];
      if (selected.pickup_lat != null && selected.pickup_lon != null) pts.push([selected.pickup_lat, selected.pickup_lon]);
      if (selected.delivery_lat != null && selected.delivery_lon != null) pts.push([selected.delivery_lat, selected.delivery_lon]);
      if (pts.length > 1) map.setBounds(ymaps.util.bounds.fromPoints(pts), { checkZoomRange: true, zoomMargin: [80, 40, 300, 40], duration: 300 });
      else map.setCenter(pts[0], 11, { duration: 300 });
    });
    // Faqat tanlov o'zgarganda — pollingda xarita sakramasin
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, mapRef, selectedId]);

  function resetUzbekistanView() {
    setSelectedId(null);
    setLocationError(null);
    fittedRef.current = true;
    mapRef.current?.setBounds(overviewBoundsRef.current, { checkZoomRange: true, zoomMargin: [24, 20, 24, 20], duration: 300 });
  }

  function focusMyLocation() {
    if (locating || !mapReady || !mapRef.current) return;
    setLocationError(null);
    if (!navigator.geolocation) {
      setLocationError('Lokatsiya mavjud emas. Telefoningizda joylashuv xizmatini yoqing.');
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocating(false);
        mapRef.current?.setCenter([coords.latitude, coords.longitude], 15, { duration: 300 });
      },
      (error) => {
        setLocating(false);
        setLocationError(error.code === 1
          ? 'Joylashuvga ruxsat berilmagan. Telefon yoki Telegram sozlamalaridan lokatsiyaga ruxsat bering.'
          : error.code === 3
            ? 'Joylashuv aniqlanmadi. GPS va internetni tekshirib qayta urinib ko‘ring.'
            : 'Joylashuv aniqlanmadi. Telefoningizda lokatsiyani yoqing.');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 },
    );
  }

  const cargoCount = items.filter((i) => i.has_cargo).length;
  const emptyCount = items.length - cargoCount;

  return (
    <div className={styles.page}>
      <div ref={containerRef} className={styles.map} />
      {!mapReady && !mapFailed && <div className={styles.mapStatus}>Xarita yuklanmoqda…</div>}
      {mapFailed && <div className={styles.mapStatus}>Xarita yuklanmadi</div>}

      <button type="button" className={styles.resetMapButton} onClick={resetUzbekistanView} disabled={!mapReady} aria-label="O‘zbekiston xaritasiga qaytish" title="Standart O‘zbekiston xaritasi">
        <span aria-hidden="true">🇺🇿</span>
      </button>
      <button type="button" className={styles.locateButton} onClick={focusMyLocation} disabled={!mapReady || locating} aria-label="Mening joylashuvim" title="Mening joylashuvim">
        <LocationIcon size={23} />
      </button>
      {locationError && <div className={styles.locationError} role="alert">{locationError}<button type="button" onClick={() => setLocationError(null)} aria-label="Xabarni yopish"><CloseIcon size={15} /></button></div>}

      <div className={styles.topPanel}>
        <div className={styles.modes} role="tablist" aria-label="Mashinalar holati">
          {MODES.map((m) => (
            <button key={m.value} role="tab" aria-selected={filter.mode === m.value}
              className={filter.mode === m.value ? styles.modeActive : styles.mode}
              onClick={() => updateFilter({ mode: m.value, fromRegion: null, toRegion: null, truckTypeId: null })}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.counter} aria-live="polite">
        {loadError
          ? 'Yangilab bo‘lmadi'
          : data
            ? [
                filter.mode !== 'empty' ? `${cargoCount} ta yukli` : null,
                filter.mode !== 'in_transit' ? `${emptyCount} ta bo'sh` : null,
              ]
                .filter(Boolean)
                .join(' · ')
            : 'Yuklanmoqda…'}
      </div>

      {selected && <SelectedCard item={selected} onClose={() => setSelectedId(null)} />}

      {role === 'driver' ? <DriverBottomNav /> : <BottomNav />}
    </div>
  );
}

function SelectedCard({ item, onClose }: { item: LiveMapItem; onClose: () => void }) {
  const load = item.load_percent != null ? Math.min(item.load_percent, 100) : null;
  return (
    <div className={styles.card} role="dialog" aria-label="Mashina ma'lumotlari">
      <button className={styles.cardClose} onClick={onClose} aria-label="Yopish">
        <CloseIcon size={16} />
      </button>

      <div className={styles.cardHead}>
        {item.truck_type_image_url ? (
          <img className={styles.truckImg} src={staticFileUrl(item.truck_type_image_url)} alt="" />
        ) : (
          <div className={styles.truckImgEmpty} />
        )}
        <div>
          <div className={styles.truckName}>{item.truck_type_name ?? 'Mashina'}</div>
          <div className={styles.muted}>
            {item.has_cargo ? 'Yuk bilan yo‘lda' : 'Bo‘sh'}
            {item.current_region && ` · hozir: ${shortRegion(item.current_region)}`}
          </div>
        </div>
      </div>

      {item.has_cargo ? (
        <>
          <div className={styles.loadRow}>
            <WeightIcon />
            <span>
              Yuklangan: <strong>{tons(item.weight)}</strong>
              {item.truck_max_weight != null && <> / {tons(item.truck_max_weight)}</>}
            </span>
            {item.cargo_name && <span className={styles.muted}>· {item.cargo_name}</span>}
          </div>
          {load != null && (
            <div className={styles.loadBar} aria-label={`Sig'im ${item.load_percent}% to'lgan`}>
              <div
                className={styles.loadFill}
                style={{ width: `${load}%`, background: (item.load_percent ?? 0) > 100 ? 'var(--color-danger)' : undefined }}
              />
            </div>
          )}

          <div className={styles.route}>
            <div className={styles.routePoint}>
              <span className={styles.dotA}>A</span>
              <div>
                <div className={styles.region}>{item.pickup_region ?? 'Yuk olish'}</div>
                <div className={styles.address}>{shortAddress(item.pickup_address) || '—'}</div>
              </div>
            </div>
            <div className={styles.routePoint}>
              <span className={styles.dotB}>B</span>
              <div>
                <div className={styles.region}>{item.delivery_region ?? 'Yuk tushirish'}</div>
                <div className={styles.address}>{shortAddress(item.delivery_address) || '—'}</div>
              </div>
            </div>
          </div>

          <div className={styles.facts}>
            <div>
              <div className={styles.factLabel}>
                <RouteIcon size={12} /> Masofa
              </div>
              <div className={styles.factValue}>{item.distance_km != null ? `${Math.round(Number(item.distance_km))} km` : '—'}</div>
            </div>
            <div>
              <div className={styles.factLabel}>Narx</div>
              <div className={styles.factValue}>{item.price != null ? `${formatPrice(Number(item.price))} so'm` : '—'}</div>
            </div>
            <div>
              <div className={styles.factLabel}>1 tonna</div>
              <div className={styles.factValue}>{item.price_per_ton != null ? formatPrice(Number(item.price_per_ton)) : '—'}</div>
            </div>
          </div>
        </>
      ) : (
        <div className={styles.muted}>
          Sig'im: {tons(item.truck_max_weight)}. Bu mashina hozir yuksiz.
        </div>
      )}
    </div>
  );
}
