import { useEffect, useRef, useState } from 'react';
import { wsUrl } from '../api/client';

/** WS qayta ulanish: 2s, 4s, 8s ... 30s gacha. */
const RECONNECT_MIN_MS = 2_000;
const RECONNECT_MAX_MS = 30_000;

interface Options {
  /** WS yo'li (`wsUrl` ga beriladi), masalan `/drivers/ws/dispatch`. */
  path: string;
  /** Server yuboradigan o'zgarish hodisasi nomi (`dispatch_changed`, `order_changed`). */
  changeEvent: string;
  /** `true` bo'lganda ulanish ochiq turadi, `false` — yopiladi. */
  enabled: boolean;
  /** Ulanish ochilganda va har o'zgarish signalida chaqiriladi. */
  onSignal: () => void;
}

/**
 * "Signal" WebSocket'i: server faqat "o'zgardi" deydi (`{event: changeEvent}`), ma'lumotning
 * o'zi oddiy REST so'rov bilan olinadi — ruxsat va serializatsiya backend'da bitta joyda
 * qoladi. Ulanish ochilganda (`connected`) ham `onSignal` chaqiriladi: oraliqda o'tkazib
 * yuborilgan o'zgarish bo'lsa ham ekran yangilanadi. Uzilsa eksponensial kechikish bilan
 * qayta ulanadi. `connected` — chaqiruvchi ulanish yo'q paytda zaxira so'rovni tezlashtirishi
 * uchun (hook'lar `useDispatchSignal`, `useOrderUpdates`).
 */
export function useSignalSocket({ path, changeEvent, enabled, onSignal }: Options): { connected: boolean } {
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
        socket = new WebSocket(wsUrl(path));
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
        } else if (event === changeEvent) {
          onSignalRef.current();
        }
        // `ping` — server ulanishni tirik ushlab turadi, javob shart emas.
      });
      socket.addEventListener('close', (ev) => {
        setConnected(false);
        // 4403/4401 — ruxsat yo'q yoki token yaroqsiz: qayta urinish befoyda (sahifa
        // zaxira so'rov bilan ishlayveradi, token yangilansa keyingi ochilishda ulanadi).
        if (!closedByUs && ev.code !== 4403) scheduleReconnect();
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
  }, [enabled, path, changeEvent]);

  return { connected };
}
