import { useEffect, useRef, useState } from 'react';
import { wsUrl } from '../api/client';

/** WS qayta ulanish: 2s, 4s, 8s ... 30s gacha. */
const RECONNECT_MIN_MS = 2_000;
const RECONNECT_MAX_MS = 30_000;

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
 * endi faqat signal kelganda (va ulanish ochilganda — oraliqda o'tkazib yuborilgan
 * o'zgarish bo'lsa). `connected` — chaqiruvchi ulanish yo'q paytda tez-tez so'rashga
 * qaytishi uchun.
 */
export function useDispatchSignal({ enabled, onSignal }: Options): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  // Har renderda yangi funksiya kelsa ham ulanish qayta ochilmasin.
  const onSignalRef = useRef(onSignal);
  useEffect(() => {
    onSignalRef.current = onSignal;
  }, [onSignal]);

  useEffect(() => {
    if (!enabled) {
      setConnected(false);
      return;
    }

    let closedByUs = false;
    let attempt = 0;
    let reconnectTimer: number | undefined;
    let socket: WebSocket | null = null;

    const scheduleReconnect = () => {
      if (closedByUs) return;
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_MIN_MS * 2 ** attempt);
      attempt += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    };

    function connect() {
      try {
        // Token har ulanishda qayta o'qiladi — yangilangan token bilan ulanadi.
        socket = new WebSocket(wsUrl('/drivers/ws/dispatch'));
      } catch {
        scheduleReconnect();
        return;
      }
      socket.addEventListener('message', (ev) => {
        let event: unknown;
        try {
          event = (JSON.parse(String(ev.data)) as { event?: unknown }).event;
        } catch {
          return;
        }
        if (event === 'connected') {
          attempt = 0;
          setConnected(true);
          onSignalRef.current();
        } else if (event === 'dispatch_changed') {
          onSignalRef.current();
        }
        // `ping` — server ulanishni tirik ushlab turadi, javob shart emas.
      });
      socket.addEventListener('close', () => {
        setConnected(false);
        if (!closedByUs) scheduleReconnect();
      });
    }

    connect();

    return () => {
      closedByUs = true;
      window.clearTimeout(reconnectTimer);
      setConnected(false);
      try {
        socket?.close();
      } catch {
        // allaqachon yopilgan
      }
    };
  }, [enabled]);

  return { connected };
}
