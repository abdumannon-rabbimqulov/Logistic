import type { DriverMonitorItem } from '../../types/api';

export type DriverVisualStatus = 'in_transit' | 'empty' | 'waiting' | 'busy' | 'stale';
export const DRIVER_STATUS_COLORS: Record<DriverVisualStatus, string> = {
  in_transit: '#2563EB', empty: '#16A34A', waiting: '#D97706', busy: '#7C3AED', stale: '#8A93A2',
};
export const DRIVER_STATUS_LABELS: Record<DriverVisualStatus, string> = {
  in_transit: 'Yuk bilan yo‘lda', empty: 'Bo‘sh mashina', waiting: 'Kutayotgan', busy: 'Band', stale: 'GPS ma’lumoti eskirgan',
};

export function driverStatus(driver: DriverMonitorItem, now: number): DriverVisualStatus {
  const timestamp = driver.location_at ? Date.parse(driver.location_at) : 0;
  if (!navigator.onLine || !driver.online || driver.location_source === 'last_known' || !timestamp || now - timestamp > 120_000) return 'stale';
  if (driver.active_order?.status === 'IN_PROGRESS') return 'in_transit';
  if (driver.active_order?.status === 'SCHEDULED') return 'waiting';
  if (driver.active_order?.status === 'ACCEPTED' || driver.busy) return 'busy';
  if (driver.online && !driver.busy) return 'empty';
  return 'busy';
}

export function driverMarkerColor(driver: DriverMonitorItem): string {
  return DRIVER_STATUS_COLORS[driverStatus(driver, Date.now())];
}

export function driverStatusLabel(driver: DriverMonitorItem): string {
  return DRIVER_STATUS_LABELS[driverStatus(driver, Date.now())];
}
