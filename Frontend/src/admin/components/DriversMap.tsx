import { useEffect, useMemo, useRef, useState } from 'react';
import type { Feature, Point } from 'geojson';
import type { GeoJSONFeatureDiff, GeoJSONSource } from 'maplibre-gl';
import { useMapLibreMap } from '../../hooks/useMapLibreMap';
import type { DriverMonitorItem } from '../../types/api';
import { driverStatus, DRIVER_STATUS_COLORS, DRIVER_STATUS_LABELS, type DriverVisualStatus } from './driverMapStatus';
import styles from './DriversMap.module.css';

const SELECTED_ZOOM = 13;

export function DriversMap({ drivers, selectedId, onSelect }: { drivers: DriverMonitorItem[]; selectedId: number | null; onSelect: (id: number | null) => void }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { mapRef, ready, failed } = useMapLibreMap(containerRef, { minZoom: 4 });
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const fittedRef = useRef(false);
  const previousRef = useRef<Map<number, Feature<Point>>>(new Map());
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    const updateOnline = () => setNow(Date.now());
    window.addEventListener('online', updateOnline);
    window.addEventListener('offline', updateOnline);
    return () => { window.clearInterval(timer); window.removeEventListener('online', updateOnline); window.removeEventListener('offline', updateOnline); };
  }, []);

  const features = useMemo(() => drivers.filter((d) => d.latitude != null && d.longitude != null).map((driver) => {
    const status = driverStatus(driver, now);
    return {
      type: 'Feature', id: driver.driver_id,
      geometry: { type: 'Point', coordinates: [driver.longitude!, driver.latitude!] },
      properties: {
        driverId: driver.driver_id, status, color: DRIVER_STATUS_COLORS[status], icon: status === 'in_transit' ? '↗' : status === 'waiting' ? '◷' : status === 'busy' ? '●' : status === 'stale' ? '!' : '✓',
        selected: selectedId === driver.driver_id,
        title: `${driver.full_name ?? `Haydovchi #${driver.driver_id}`} · ${driver.truck_number}`,
      },
    } satisfies Feature<Point>;
  }), [drivers, now, selectedId]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (!map.getSource('drivers')) {
      map.addSource('drivers', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, cluster: true, clusterMaxZoom: 11, clusterRadius: 42 });
      map.addLayer({ id: 'driver-clusters', type: 'circle', source: 'drivers', filter: ['has', 'point_count'], paint: { 'circle-color': '#0F1319', 'circle-radius': ['step', ['get', 'point_count'], 18, 20, 23, 50, 28], 'circle-stroke-width': 2, 'circle-stroke-color': '#fff' } });
      map.addLayer({ id: 'driver-cluster-count', type: 'symbol', source: 'drivers', filter: ['has', 'point_count'], layout: { 'text-field': '{point_count_abbreviated}', 'text-size': 11 }, paint: { 'text-color': '#fff' } });
      map.addLayer({ id: 'driver-points', type: 'circle', source: 'drivers', filter: ['!', ['has', 'point_count']], paint: { 'circle-color': ['get', 'color'], 'circle-radius': ['case', ['get', 'selected'], 9, 7], 'circle-stroke-width': ['case', ['get', 'selected'], 3, 2], 'circle-stroke-color': '#fff' } });
      map.addLayer({ id: 'driver-glyphs', type: 'symbol', source: 'drivers', filter: ['!', ['has', 'point_count']], layout: { 'text-field': ['get', 'icon'], 'text-size': 9, 'text-allow-overlap': true }, paint: { 'text-color': '#fff' } });
    }
    const clear = (event: { point: { x: number; y: number } }) => {
      if (!map.queryRenderedFeatures([event.point.x, event.point.y], { layers: ['driver-points', 'driver-clusters'] }).length) onSelectRef.current(null);
    };
    const selectPoint = (event: { features?: Array<{ properties?: Record<string, unknown> }> }) => {
      const id = Number(event.features?.[0]?.properties?.driverId);
      if (Number.isFinite(id)) onSelectRef.current(id);
    };
    const zoomCluster = (event: { features?: Array<{ geometry: { type: string; coordinates: [number, number] }; properties?: Record<string, unknown> }> }) => {
      const feature = event.features?.[0];
      const id = Number(feature?.properties?.cluster_id);
      if (!feature || !Number.isFinite(id)) return;
      (map.getSource('drivers') as GeoJSONSource).getClusterExpansionZoom(id).then((zoom) => map.easeTo({ center: feature.geometry.coordinates, zoom }));
    };
    map.on('click', clear);
    map.on('click', 'driver-points', selectPoint as never);
    map.on('click', 'driver-clusters', zoomCluster as never);
    map.on('mouseenter', 'driver-points', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'driver-points', () => { map.getCanvas().style.cursor = ''; });
    map.on('mouseenter', 'driver-clusters', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'driver-clusters', () => { map.getCanvas().style.cursor = ''; });
    return () => { map.off('click', clear); map.off('click', 'driver-points', selectPoint as never); map.off('click', 'driver-clusters', zoomCluster as never); };
  }, [mapRef, ready]);

  useEffect(() => {
    const source = mapRef.current?.getSource('drivers') as GeoJSONSource | undefined;
    if (!source) return;
    const current = new Map(features.map((feature) => [Number(feature.id), feature]));
    const previous = previousRef.current;
    const add = [...current].filter(([id]) => !previous.has(id)).map(([, feature]) => feature);
    const remove = [...previous.keys()].filter((id) => !current.has(id));
    const update = [...current].filter(([id, feature]) => previous.has(id) && JSON.stringify(previous.get(id)) !== JSON.stringify(feature)).map(([, feature]) => ({
      id: Number(feature.id), newGeometry: feature.geometry,
      addOrUpdateProperties: Object.entries(feature.properties ?? {}).map(([key, value]) => ({ key, value })),
    } satisfies GeoJSONFeatureDiff));
    if (add.length || remove.length || update.length) void source.updateData({ add, remove, update });
    previousRef.current = current;

    if (!fittedRef.current && features.length) {
      fittedRef.current = true;
      const coordinates = features.map((feature) => feature.geometry.coordinates);
      const bounds = coordinates.reduce((result, [longitude, latitude]) => ({
        minLng: Math.min(result.minLng, longitude), minLat: Math.min(result.minLat, latitude),
        maxLng: Math.max(result.maxLng, longitude), maxLat: Math.max(result.maxLat, latitude),
      }), { minLng: coordinates[0][0], minLat: coordinates[0][1], maxLng: coordinates[0][0], maxLat: coordinates[0][1] });
      mapRef.current!.fitBounds([[bounds.minLng, bounds.minLat], [bounds.maxLng, bounds.maxLat]], { padding: 60, maxZoom: SELECTED_ZOOM, duration: 250 });
    }
  }, [mapRef, ready, features]);

  useEffect(() => {
    if (!ready || selectedId == null || selectedId < 0) return;
    const driver = drivers.find((item) => item.driver_id === selectedId);
    if (driver?.latitude != null && driver.longitude != null) mapRef.current?.easeTo({ center: [driver.longitude, driver.latitude], zoom: SELECTED_ZOOM, duration: 300 });
    // Deliberately only react to selection; GPS refreshes must not recenter the map.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, selectedId]);

  return <div className={styles.wrap}>
    <div ref={containerRef} className={styles.map} />
    {!ready && !failed && <div className={styles.spinner} aria-label="Xarita yuklanmoqda" />}
    {failed && <div className={styles.error}>Xarita yuklanmadi</div>}
    <div className={styles.legend} aria-label="Haydovchi holatlari">
      {(['in_transit', 'empty', 'waiting', 'busy', 'stale'] as DriverVisualStatus[]).map((status) => <span className={styles.legendItem} key={status}>
        <i className={styles.legendDot} style={{ background: DRIVER_STATUS_COLORS[status] }} /> {DRIVER_STATUS_LABELS[status]}
      </span>)}
    </div>
  </div>;
}
