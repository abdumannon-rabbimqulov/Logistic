import { useSignalSocket } from './useSignalSocket';

interface Options {
  orderId: number | null;
  /** Buyurtma yakuniy holatda bo'lmaganda `true` — faqat shunda ulanish ochiq turadi. */
  enabled: boolean;
  /** Ulanish ochilganda va har "buyurtma o'zgardi" signalida chaqiriladi. */
  onSignal: () => void;
}

/**
 * Buyurtma sahifasiga signal: `/orders/{id}/ws/updates` (tracking_service).
 *
 * Server faqat "o'zgardi" deydi (`{event: "order_changed"}`) — buyurtmaning o'zi
 * `GET /orders/{id}` dan olinadi. Ilgari sahifa buni har 5–10 soniyada so'rardi,
 * endi faqat signal kelganda; `connected` bo'lmasa — avvalgi polling (`OrderTrackingPage`).
 */
export function useOrderUpdates({ orderId, enabled, onSignal }: Options): { connected: boolean } {
  return useSignalSocket({
    path: `/orders/${orderId}/ws/updates`,
    changeEvent: 'order_changed',
    enabled: enabled && orderId != null && Number.isFinite(orderId),
    onSignal,
  });
}
