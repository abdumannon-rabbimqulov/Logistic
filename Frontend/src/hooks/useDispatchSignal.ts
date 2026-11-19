import { useSignalSocket } from './useSignalSocket';

interface Options {
  /** Liniyada bo'lganda `true` — faqat shunda ulanish ochiq turadi. */
  enabled: boolean;
  /** Ulanish ochilganda va har "taklif o'zgardi" signalida chaqiriladi. */
  onSignal: () => void;
}

/**
 * Haydovchiga dispatch signali: `/drivers/ws/dispatch` (tracking_service).
 *
 * Server faqat "o'zgardi" deydi (`{event: "dispatch_changed"}`) — taklifning o'zi
 * `GET /orders/dispatch/active` dan olinadi. Ilgari sahifa buni har 3 soniyada so'rardi,
 * endi faqat signal kelganda (va ulanish ochilganda). `connected` — ulanish yo'q paytda
 * tez-tez so'rashga qaytish uchun (`DriverHomePage`).
 */
export function useDispatchSignal({ enabled, onSignal }: Options): { connected: boolean } {
  return useSignalSocket({
    path: '/drivers/ws/dispatch',
    changeEvent: 'dispatch_changed',
    enabled,
    onSignal,
  });
}
