import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Feature, FeatureCollection, Point } from 'geojson';
import type { GeoJSONFeatureDiff, GeoJSONSource } from 'maplibre-gl';
import { useMapLibreMap, UZ_BOUNDS, UZ_CENTER } from '../hooks/useMapLibreMap';
import { getLiveMap } from '../api/orders';
import { staticFileUrl } from '../api/truckTypes';
import { BottomNav } from '../components/BottomNav';
import { DriverBottomNav } from '../components/DriverBottomNav';
import { CloseIcon, LocationIcon, RouteIcon, SearchIcon, WeightIcon } from '../components/icons';
import type {
  LiveMapFilter,
  LiveMapItem,
  LiveMapMode,
  LiveMapResponse,
} from '../types/api';
import { formatPrice, shortAddress } from '../utils/format';
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
type RegionFeature = Feature & { properties: { name: string; color?: string } };

// MapLibre view cheklovi: O'zbekiston to'rtburchagi davlat poligoni emas.
const MAP_BEARING = -90;

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
  const [searchText, setSearchText] = useState('');
  const [locating, setLocating] = useState(false);
  const [expandedMap, setExpandedMap] = useState(false);
  const [online, setOnline] = useState(() => navigator.onLine);
  const [now, setNow] = useState(Date.now());

  const containerRef = useRef<HTMLDivElement>(null);
  const { mapRef, moduleRef, ready: mapReady, failed: mapFailed } = useMapLibreMap(containerRef, {
    center: UZ_CENTER, zoom: 4, minZoom: 4, maxBounds: UZ_BOUNDS,
  });
  const fittedRef = useRef(false);
  const overviewBoundsRef = useRef<[[number, number], [number, number]]>(UZ_BOUNDS);

  useEffect(() => {
    const updateOnline = () => { setOnline(navigator.onLine); setNow(Date.now()); };
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    window.addEventListener('online', updateOnline);
    window.addEventListener('offline', updateOnline);
    return () => { window.clearInterval(timer); window.removeEventListener('online', updateOnline); window.removeEventListener('offline', updateOnline); };
  }, []);

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
  const visibleItems = useMemo(() => {
    const query = searchText.trim().toLocaleLowerCase();
    if (!query) return items;
    return items.filter((item) => [item.truck_type_name, item.cargo_name, item.current_region, item.pickup_address, item.delivery_address]
      .some((value) => value?.toLocaleLowerCase().includes(query)));
  }, [items, searchText]);
  const selected = useMemo(() => visibleItems.find((i) => i.marker_id === selectedId) ?? null, [visibleItems, selectedId]);
  const dataStale = Boolean(data && (loadError || !online || now - Date.parse(data.generated_at) > 120_000));

  // Xarita qatlamlari bir marta o'rnatiladi; GPS oqimi faqat GeoJSON source'ni yangilaydi.
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !moduleRef.current) return;
    if (!map.getSource('uz-regions')) map.addSource('uz-regions', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    if (!map.getLayer('uz-regions-fill')) map.addLayer({ id: 'uz-regions-fill', type: 'fill', source: 'uz-regions', paint: { 'fill-color': ['coalesce', ['get', 'color'], '#DCEFE7'], 'fill-opacity': 0.3 } });
    if (!map.getLayer('uz-regions-line')) map.addLayer({ id: 'uz-regions-line', type: 'line', source: 'uz-regions', paint: { 'line-color': '#64748B', 'line-width': 1.3, 'line-opacity': 0.9 } });
    if (!map.getSource('live-markers')) map.addSource('live-markers', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, cluster: true, clusterMaxZoom: 11, clusterRadius: 38 });
    if (!map.getLayer('live-clusters')) map.addLayer({ id: 'live-clusters', type: 'circle', source: 'live-markers', filter: ['has', 'point_count'], paint: { 'circle-color': '#0F1319', 'circle-radius': ['step', ['get', 'point_count'], 18, 20, 22, 50, 27], 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });
    if (!map.getLayer('live-cluster-count')) map.addLayer({ id: 'live-cluster-count', type: 'symbol', source: 'live-markers', filter: ['has', 'point_count'], layout: { 'text-field': '{point_count_abbreviated}', 'text-size': 11 }, paint: { 'text-color': '#fff' } });
    if (!map.getLayer('live-points')) map.addLayer({ id: 'live-points', type: 'circle', source: 'live-markers', filter: ['!', ['has', 'point_count']], paint: { 'circle-color': ['case', ['get', 'stale'], '#8A93A2', ['get', 'hasCargo'], ['case', ['get', 'selected'], '#0F1319', CARGO_COLOR], EMPTY_COLOR], 'circle-radius': ['case', ['get', 'selected'], 9, 7], 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });
    if (!map.getSource('selected-route')) map.addSource('selected-route', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    if (!map.getLayer('selected-route-line')) map.addLayer({ id: 'selected-route-line', type: 'line', source: 'selected-route', paint: { 'line-color': CARGO_COLOR, 'line-width': 3, 'line-opacity': 0.75, 'line-dasharray': [2, 2] } });
    map.moveLayer('selected-route-line', 'live-clusters');
    const clear = (event: { point: { x: number; y: number } }) => {
      const hit = map.queryRenderedFeatures([event.point.x, event.point.y], { layers: ['live-points', 'live-clusters'] });
      if (!hit.length) setSelectedId(null);
    };
    const clickPoint = (event: { features?: Array<{ properties?: Record<string, unknown> }> }) => {
      const id = event.features?.[0]?.properties?.markerId;
      if (typeof id === 'string') setSelectedId(id);
    };
    const clickCluster = (event: { features?: Array<{ geometry: { coordinates: [number, number] }; properties?: Record<string, unknown> }> }) => {
      const feature = event.features?.[0];
      const clusterId = feature?.properties?.cluster_id;
      if (typeof clusterId !== 'number' || !feature) return;
      (map.getSource('live-markers') as GeoJSONSource).getClusterExpansionZoom(clusterId).then((zoom) => map.easeTo({ center: feature.geometry.coordinates, zoom }));
    };
    map.on('click', clear);
    map.on('click', 'live-points', clickPoint as never);
    map.on('click', 'live-clusters', clickCluster as never);
    map.on('mouseenter', 'live-points', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'live-points', () => { map.getCanvas().style.cursor = ''; });
    map.on('mouseenter', 'live-clusters', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'live-clusters', () => { map.getCanvas().style.cursor = ''; });
    return () => { map.off('click', clear); map.off('click', 'live-points', clickPoint as never); map.off('click', 'live-clusters', clickCluster as never); };
  }, [mapReady, mapRef, moduleRef]);

  useEffect(() => {
    const source = mapRef.current?.getSource('uz-regions') as GeoJSONSource | undefined;
    if (!source || !regionShapes.length) return;
    source.setData({ type: 'FeatureCollection', features: regionShapes.map((feature, index) => ({ ...feature, properties: { ...feature.properties, color: REGION_COLORS[index % REGION_COLORS.length] } })) } as FeatureCollection);
  }, [mapReady, mapRef, regionShapes]);

  const markerFeatures: Feature<Point>[] = useMemo(() => visibleItems.map((item) => ({
    type: 'Feature', id: item.marker_id, geometry: { type: 'Point', coordinates: [item.lon, item.lat] },
    properties: { markerId: item.marker_id, hasCargo: item.has_cargo, selected: item.marker_id === selectedId, stale: dataStale, truck: item.truck_type_name ?? 'Mashina' },
  })), [visibleItems, selectedId, dataStale]);
  const previousMarkersRef = useRef<Map<string, Feature<Point>>>(new Map());
  useEffect(() => {
    const source = mapRef.current?.getSource('live-markers') as GeoJSONSource | undefined;
    if (!source) return;
    const current = new Map(markerFeatures.map((feature) => [String(feature.id), feature]));
    const previous = previousMarkersRef.current;
    const add = [...current].filter(([id]) => !previous.has(id)).map(([, feature]) => feature);
    const remove = [...previous.keys()].filter((id) => !current.has(id));
    const update = [...current].filter(([id, feature]) => previous.has(id) && JSON.stringify(previous.get(id)) !== JSON.stringify(feature)).map(([, feature]) => ({
      id: feature.id as string,
      newGeometry: feature.geometry,
      addOrUpdateProperties: Object.entries(feature.properties ?? {}).map(([key, value]) => ({ key, value })),
    } satisfies GeoJSONFeatureDiff));
    if (add.length || remove.length || update.length) void source.updateData({ add, remove, update });
    previousMarkersRef.current = current;

    const selectedItem = visibleItems.find((item) => item.marker_id === selectedId);
    const coords = selectedItem?.has_cargo && selectedItem.pickup_lat != null && selectedItem.pickup_lon != null && selectedItem.delivery_lat != null && selectedItem.delivery_lon != null
      ? [[selectedItem.pickup_lon, selectedItem.pickup_lat], [selectedItem.lon, selectedItem.lat], [selectedItem.delivery_lon, selectedItem.delivery_lat]]
      : [];
    (mapRef.current?.getSource('selected-route') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: coords.length ? [{ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: coords } }] : [] });
  }, [mapReady, mapRef, markerFeatures, visibleItems, selectedId]);

  const fitUzbekistan = useCallback((duration = 250, padding: number | [number, number, number, number] = 24) => {
    const map = mapRef.current;
    if (!map) return;
    const pad = typeof padding === 'number' ? { top: padding, right: padding, bottom: padding, left: padding } : { top: padding[0], right: padding[1], bottom: padding[2], left: padding[3] };
    const camera = map.cameraForBounds(overviewBoundsRef.current, { bearing: MAP_BEARING, padding: pad, maxZoom: 6 });
    if (camera) map.easeTo({ ...camera, duration });
  }, [mapRef]);

  // Mamlakatning barcha chegaralarini telefon ekraniga aylantirilgan kamera bilan sig'dirish.
  useEffect(() => {
    if (!mapReady || !mapRef.current || !regionShapes.length || fittedRef.current) return;
    const coords: [number, number][] = [];
    for (const feature of regionShapes) {
      const geometry = feature.geometry;
      const polygons = geometry.type === 'MultiPolygon' ? geometry.coordinates : geometry.type === 'Polygon' ? [geometry.coordinates] : [];
      for (const polygon of polygons) for (const ring of polygon)
        for (const [lon, lat] of ring) coords.push([lat, lon]);
    }
    if (!coords.length) return;
    let minLat = 90, minLon = 180, maxLat = -90, maxLon = -180;
    for (const [lat, lon] of coords) {
      minLat = Math.min(minLat, lat); maxLat = Math.max(maxLat, lat);
      minLon = Math.min(minLon, lon); maxLon = Math.max(maxLon, lon);
    }
    overviewBoundsRef.current = [[minLon, minLat], [maxLon, maxLat]];
    fittedRef.current = true;
    fitUzbekistan(0, [24, 24, 24, 24]);
  }, [mapReady, mapRef, regionShapes, fitUzbekistan]);

  // Tanlangan yuk to'liq ko'rinsin: A, mashina, B
  useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map || !selected) return;
    const pts: [number, number][] = [[selected.lon, selected.lat]];
    if (selected.pickup_lat != null && selected.pickup_lon != null) pts.push([selected.pickup_lon, selected.pickup_lat]);
    if (selected.delivery_lat != null && selected.delivery_lon != null) pts.push([selected.delivery_lon, selected.delivery_lat]);
    if (pts.length > 1) {
      const bounds = pts.slice(1).reduce((result, point) => result.extend(point), new (moduleRef.current!.LngLatBounds)(pts[0], pts[0]));
      const camera = map.cameraForBounds(bounds, { bearing: MAP_BEARING, padding: { top: 80, right: 40, bottom: 300, left: 40 }, maxZoom: 12 });
      if (camera) map.easeTo({ ...camera, duration: 300 });
    } else map.easeTo({ center: pts[0], zoom: 11, duration: 300 });
    // Faqat tanlov o'zgarganda — pollingda xarita sakramasin
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, mapRef, selectedId, moduleRef]);

  function showUzbekistanOverview() {
    const map = mapRef.current;
    if (!map) return;
    map.resize();
    fitUzbekistan(250, [12, 12, 12, 12]);
  }

  useEffect(() => {
    if (!mapReady) return;
    const id = window.requestAnimationFrame(() => showUzbekistanOverview());
    return () => window.cancelAnimationFrame(id);
    // Faqat to‘liq ekran holati almashganda.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedMap, mapReady]);

  function resetUzbekistanView() {
    setSelectedId(null);
    setLocationError(null);
    fittedRef.current = true;
    showUzbekistanOverview();
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
        mapRef.current?.easeTo({ center: [coords.longitude, coords.latitude], zoom: 15, duration: 300 });
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

  const cargoCount = visibleItems.filter((i) => i.has_cargo).length;
  const emptyCount = visibleItems.length - cargoCount;

  return (
    <div className={`${styles.page} ${expandedMap ? styles.expandedPage : ''}`}>
      <div ref={containerRef} className={styles.map} />
      {!mapReady && !mapFailed && <div className={styles.mapStatus}>Xarita yuklanmoqda…</div>}
      {mapFailed && <div className={styles.mapStatus}>Xarita yuklanmadi</div>}

      <button type="button" className={styles.expandMapButton} onClick={() => setExpandedMap((prev) => !prev)} aria-label={expandedMap ? 'Oddiy xaritaga qaytish' : 'Xaritani kengaytirish'} title={expandedMap ? 'Oddiy ko‘rinish' : 'To‘liq xarita'}>
        {expandedMap ? '↙' : '⛶'}
      </button>
      <button type="button" className={styles.resetMapButton} onClick={resetUzbekistanView} disabled={!mapReady} aria-label="O‘zbekiston xaritasiga qaytish" title="Standart O‘zbekiston xaritasi">
        <span aria-hidden="true">🇺🇿</span>
      </button>
      <button type="button" className={styles.locateButton} onClick={focusMyLocation} disabled={!mapReady || locating} aria-label="Mening joylashuvim" title="Mening joylashuvim">
        <LocationIcon size={23} />
      </button>
      {locationError && <div className={styles.locationError} role="alert">{locationError}<button type="button" onClick={() => setLocationError(null)} aria-label="Xabarni yopish"><CloseIcon size={15} /></button></div>}

      {!expandedMap && <div className={styles.topPanel}>
        <label className={styles.searchBox}>
          <SearchIcon size={18} />
          <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="Mashina yoki manzilni qidiring" aria-label="Mashina yoki manzilni qidirish" />
          {searchText && <button type="button" onClick={() => setSearchText('')} aria-label="Qidiruvni tozalash">×</button>}
        </label>
        <div className={styles.modes} role="tablist" aria-label="Mashinalar holati">
          {MODES.map((m) => (
            <button key={m.value} role="tab" aria-selected={filter.mode === m.value}
              className={filter.mode === m.value ? styles.modeActive : styles.mode}
              onClick={() => updateFilter({ mode: m.value, fromRegion: null, toRegion: null, truckTypeId: null })}>
              {m.label}
            </button>
          ))}
        </div>
      </div>}

      {!expandedMap && <div className={styles.counter} aria-live="polite">
        {dataStale
          ? 'Yangilanish yo‘q — oxirgi ma’lumot eskirgan'
          : loadError
            ? 'Ma’lumot yuklanmadi — internetni tekshiring'
          : data
            ? [
                filter.mode !== 'empty' ? `${cargoCount} ta yukli` : null,
                filter.mode !== 'in_transit' ? `${emptyCount} ta bo'sh` : null,
              ]
                .filter(Boolean)
                .join(' · ')
            : 'Yuklanmoqda…'}
      </div>}

      {selected && <SelectedCard item={selected} stale={dataStale} onClose={() => setSelectedId(null)} />}

      {!expandedMap && (role === 'driver' ? <DriverBottomNav /> : <BottomNav />)}
    </div>
  );
}

function SelectedCard({ item, stale, onClose }: { item: LiveMapItem; stale: boolean; onClose: () => void }) {
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
            {stale ? 'Ma’lumot eskirgan' : item.has_cargo ? 'Yuk bilan yo‘lda' : 'Bo‘sh'}
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
