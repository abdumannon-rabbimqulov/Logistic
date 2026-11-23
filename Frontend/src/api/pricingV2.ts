import { api } from './client';

export interface PricingV2Costs {
  fuel_uzs_per_liter: string;
  loaded_liters_per_100_km: string;
  empty_liters_per_100_km: string;
  operation_uzs_per_km: string;
  driving_uzs_per_hour: string;
  loading_uzs_per_hour: string;
  unloading_uzs_per_hour: string;
  waiting_uzs_per_hour: string;
  handling_uzs_per_ton: string;
  handling_uzs_per_m3: string;
}

export interface PricingV2Bounds { minimum: string; maximum: string }

export interface PricingV2Rules {
  minimum_price_uzs: string;
  target_margin_uzs: string;
  minimum_net_margin_uzs: string;
  commission_rate: string;
  route_bounds: PricingV2Bounds;
  demand_bounds: PricingV2Bounds;
}

export interface PricingV2Draft {
  costs: PricingV2Costs;
  rules: PricingV2Rules;
  configured_empty_run: { distance_km: string; duration_min: string } | null;
}

export interface PricingV2Version {
  id: number;
  version: number;
  status: 'draft' | 'published';
  profile: PricingV2Draft;
  created_at: string;
  published_at: string | null;
}

export interface PricingV2PreviewRequest {
  profile: PricingV2Draft;
  distance_km: string;
  duration_min: string;
  weight_t: string;
  volume_m3: string | null;
  loading_min: string;
  unloading_min: string;
  waiting_min: string;
  regional_factor: string;
  demand_signal: string;
}

export interface PricingV2Result {
  recommended_price: string;
  expected_commission: string;
  expected_net_margin: string;
  costs: { total: string; fuel: string; operation: string; empty_run: string; driver_time: string };
  tariff_version_id: number;
}

const root = (id: number) => `/system/pricing-v2/truck-types/${id}`;

export const listPricingV2Versions = (id: number) => api.get<PricingV2Version[]>(root(id));
export const savePricingV2Draft = (id: number, draft: PricingV2Draft) =>
  api.put<{ id: number; version: number; status: string }>(root(id) + '/draft', draft);
export const previewPricingV2 = (id: number, preview: PricingV2PreviewRequest) =>
  api.post<PricingV2Result>(root(id) + '/preview', preview);
export const publishPricingV2 = (id: number) =>
  api.post<{ id: number; version: number; status: string; active_in_orders: boolean }>(root(id) + '/publish');

export interface LegacyPricingPreviewInput {
  base_price: string;
  price_per_km: string;
  price_per_ton_km: string;
  min_price: string | null;
  distance_km: string;
  weight_t: string;
}
export const previewLegacyPricing = (input: LegacyPricingPreviewInput) =>
  api.post<{ price: string; billable_distance_km: number }>('/system/pricing-v2/legacy-preview', input);
