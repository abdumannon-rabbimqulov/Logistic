// Kept behind dynamic import so the general app shell and non-map routes do not
// download the WebGL renderer until a map surface is mounted.
export { Map, Marker, LngLatBounds } from 'maplibre-gl';
