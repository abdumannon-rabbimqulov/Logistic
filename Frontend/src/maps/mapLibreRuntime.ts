// Kept behind dynamic import so the general app shell and non-map routes do not
// download the WebGL renderer until a map surface is mounted.
import { setWorkerUrl } from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';

// MapLibre's default URL points next to its module, which Vite bundles separately.
setWorkerUrl(workerUrl);

export { Map, Marker, LngLatBounds } from 'maplibre-gl';
