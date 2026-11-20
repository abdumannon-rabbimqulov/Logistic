import { useEffect, useRef, useState, type RefObject } from 'react';
import type { Map as MapLibreMapInstance, MapOptions } from 'maplibre-gl';

export const UZ_CENTER: [number, number] = [64.585262, 41.377491];
export const UZ_BOUNDS: [[number, number], [number, number]] = [[55.9, 37.1], [73.2, 45.6]];
export const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL || 'https://tiles.openfreemap.org/styles/liberty';

interface Options extends Partial<MapOptions> {
  styleUrl?: string;
}

export function useMapLibreMap(containerRef: RefObject<HTMLDivElement | null>, options: Options = {}) {
  const mapRef = useRef<MapLibreMapInstance | null>(null);
  const moduleRef = useRef<typeof import('../maps/mapLibreRuntime') | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!containerRef.current) return;
    let cancelled = false;
    let loaded = false;
    let map: MapLibreMapInstance | null = null;
    const { styleUrl, ...mapOptions } = options;
    void Promise.all([import('../maps/mapLibreRuntime'), import('maplibre-gl/dist/maplibre-gl.css')]).then(([module]) => {
      if (cancelled || !containerRef.current) return;
      try {
        const { Map } = module;
        moduleRef.current = module;
        map = new Map({
          container: containerRef.current,
          style: styleUrl ?? MAP_STYLE_URL,
          center: options.center ?? UZ_CENTER,
          zoom: options.zoom ?? 5,
          minZoom: options.minZoom ?? 4,
          maxZoom: options.maxZoom ?? 18,
          maxBounds: options.maxBounds ?? UZ_BOUNDS,
          attributionControl: { compact: true },
          pitchWithRotate: false,
          dragRotate: false,
          ...mapOptions,
        });
        mapRef.current = map;
        map.once('load', () => { loaded = true; if (!cancelled) setReady(true); });
        map.on('error', (event) => {
          if (event.error && !loaded) setFailed(true);
        });
      } catch {
        setFailed(true);
      }
    }).catch(() => setFailed(true));
    return () => {
      cancelled = true;
      map?.remove();
      mapRef.current = null;
      setReady(false);
    };
    // A map instance is created once per mounted surface; callers update its data through sources.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerRef]);

  return { mapRef, moduleRef, ready, failed };
}
