import { forwardRef, useEffect, useImperativeHandle, useRef } from 'react';
import type { Feature, LineString } from 'geojson';
import { useMapLibreMap } from '../hooks/useMapLibreMap';
import styles from './MapLibreMap.module.css';

interface Point { latitude: number; longitude: number }
export interface MapLibreMapHandle { focusLocation: (latitude: number, longitude: number) => void }
interface Props {
  origin?: Point | null;
  destination?: Point | null;
  route?: [number, number][] | null;
  userLocation?: Point | null;
  driverLocation?: Point | null;
  driverStale?: boolean;
  followUser?: boolean;
  onOriginMove?: (latitude: number, longitude: number) => void;
  onDestinationMove?: (latitude: number, longitude: number) => void;
  onOriginClick?: () => void;
  onDestinationClick?: () => void;
}

function markerElement(color: string, glyph?: string) {
  const el = document.createElement('button');
  el.type = 'button';
  el.setAttribute('aria-label', glyph ? `${glyph} xarita belgisi` : 'Xarita belgisi');
  el.style.cssText = `width:30px;height:30px;border:3px solid #fff;border-radius:50%;background:${color};box-shadow:0 2px 8px #0f172a55;color:white;font-size:13px;font-weight:700;display:grid;place-items:center;cursor:pointer`;
  if (glyph) el.textContent = glyph;
  return el;
}

export const MapLibreMap = forwardRef<MapLibreMapHandle, Props>(function MapLibreMap(props, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { mapRef, moduleRef, ready, failed } = useMapLibreMap(containerRef);
  const markersRef = useRef<Map<string, { marker: import('maplibre-gl').Marker; lat: number; lon: number; appearance: string }>>(new Map());
  const centeredOnUserRef = useRef(false);
  const mapInstanceRef = useRef<import('maplibre-gl').Map | null>(null);
  const cameraSignatureRef = useRef('');
  const routeSignatureRef = useRef('');
  const callbacksRef = useRef({ onOriginMove: props.onOriginMove, onDestinationMove: props.onDestinationMove, onOriginClick: props.onOriginClick, onDestinationClick: props.onDestinationClick });
  callbacksRef.current = { onOriginMove: props.onOriginMove, onDestinationMove: props.onDestinationMove, onOriginClick: props.onOriginClick, onDestinationClick: props.onDestinationClick };

  useImperativeHandle(ref, () => ({
    focusLocation: (latitude, longitude) => mapRef.current?.easeTo({ center: [longitude, latitude], zoom: 16, duration: 300 }),
  }), [mapRef]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !moduleRef.current) return;
    const { Marker, LngLatBounds } = moduleRef.current;
    if (mapInstanceRef.current !== map) {
      markersRef.current.forEach(({ marker }) => marker.remove());
      markersRef.current.clear();
      mapInstanceRef.current = map;
      cameraSignatureRef.current = '';
      routeSignatureRef.current = '';
    }
    const routeGeo: Feature<LineString> = {
      type: 'Feature', properties: {},
      geometry: { type: 'LineString', coordinates: (props.route ?? []).map(([lat, lon]) => [lon, lat]) },
    };
    const routeSignature = JSON.stringify(props.route ?? []);
    if (!map.getSource('route')) {
      map.addSource('route', { type: 'geojson', data: routeGeo });
      map.addLayer({ id: 'route-casing', type: 'line', source: 'route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#FFFFFF', 'line-width': 8, 'line-opacity': 0.9 } });
      map.addLayer({ id: 'route-line', type: 'line', source: 'route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#15803D', 'line-width': 4 } });
      routeSignatureRef.current = routeSignature;
    } else if (routeSignature !== routeSignatureRef.current) {
      (map.getSource('route') as import('maplibre-gl').GeoJSONSource).setData(routeGeo);
      routeSignatureRef.current = routeSignature;
    }

    const desired = [
      { key: 'origin', point: props.origin, color: '#16A34A', glyph: 'A', draggable: callbacksRef.current.onOriginMove, onClick: callbacksRef.current.onOriginClick },
      { key: 'destination', point: props.destination, color: '#DC2626', glyph: 'B', draggable: callbacksRef.current.onDestinationMove, onClick: callbacksRef.current.onDestinationClick },
      { key: 'user', point: props.userLocation, color: '#2563EB', glyph: '', draggable: undefined, onClick: undefined },
      { key: 'driver', point: props.driverLocation, color: props.driverStale ? '#9CA3AF' : '#F59E0B', glyph: '●', draggable: undefined, onClick: undefined },
    ].filter((item) => Boolean(item.point));
    const ids = new Set(desired.map((item) => item.key));
    for (const [key, old] of markersRef.current) if (!ids.has(key)) { old.marker.remove(); markersRef.current.delete(key); }
    for (const item of desired) {
      const point = item.point!;
      const old = markersRef.current.get(item.key);
      const appearance = `${item.color}|${item.glyph}|${Boolean(item.draggable)}`;
      if (old && old.lat === point.latitude && old.lon === point.longitude && old.appearance === appearance) continue;
      old?.marker.remove();
      const el = markerElement(item.color, item.glyph);
      if (item.draggable) {
        el.title = item.key === 'origin' ? 'Yuklash nuqtasini suring' : 'Yetkazish nuqtasini suring';
      }
      const marker = new Marker({ element: el, draggable: Boolean(item.draggable), anchor: 'bottom' })
        .setLngLat([point.longitude, point.latitude]).addTo(map);
      if (item.draggable) marker.on('dragend', () => {
        const { lat, lng } = marker.getLngLat();
        (item.key === 'origin' ? callbacksRef.current.onOriginMove : callbacksRef.current.onDestinationMove)?.(lat, lng);
      });
      if (item.onClick) el.addEventListener('click', (event) => {
        event.stopPropagation();
        (item.key === 'origin' ? callbacksRef.current.onOriginClick : callbacksRef.current.onDestinationClick)?.();
      });
      markersRef.current.set(item.key, { marker, lat: point.latitude, lon: point.longitude, appearance });
    }
    const coords = props.route && props.route.length > 1 ? props.route : desired.map(({ point }) => [point!.latitude, point!.longitude] as [number, number]);
    const cameraSignature = JSON.stringify({ route: props.route, origin: props.origin, destination: props.destination });
    if (cameraSignature !== cameraSignatureRef.current && coords.length > 1) {
      const bounds = coords.reduce((b, [lat, lon]) => b.extend([lon, lat]), new LngLatBounds([coords[0][1], coords[0][0]], [coords[0][1], coords[0][0]]));
      map.fitBounds(bounds, { bearing: map.getBearing(), padding: 48, maxZoom: 14, duration: 250 });
      cameraSignatureRef.current = cameraSignature;
    } else if (cameraSignature !== cameraSignatureRef.current && coords.length === 1 && !props.followUser) {
      map.easeTo({ center: [coords[0][1], coords[0][0]], zoom: 15, duration: 250 });
      cameraSignatureRef.current = cameraSignature;
    } else if (props.followUser && props.userLocation && !centeredOnUserRef.current) {
      centeredOnUserRef.current = true;
      map.easeTo({ center: [props.userLocation.longitude, props.userLocation.latitude], zoom: 16, duration: 300 });
    }
  }, [ready, mapRef, moduleRef, props.origin, props.destination, props.route, props.userLocation, props.driverLocation, props.driverStale, props.followUser]);

  return <div className={styles.wrap}>
    <div ref={containerRef} className={styles.map} />
    {!ready && !failed && <div className={styles.spinner} aria-label="Xarita yuklanmoqda" />}
    {failed && <div className={styles.error}>Xarita yuklanmadi</div>}
  </div>;
});
