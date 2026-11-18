import { useCallback, useEffect, useRef, useState } from 'react';
import { chatSocketUrl, type ChatMessage } from '../api/chat';
import { getAccessToken, refreshAccessToken } from '../api/client';

// Chat real vaqt kanali: `/chat/ws?token=` (chat_service/ws.py).
//
// Ulanish foydalanuvchi bo'yicha — hamma suhbatlarining hodisalari keladi, sahifa
// `order_id` bo'yicha o'zi filtrlaydi. WS tarixni saqlamaydi: har (qayta) ochilishda
// `onOpen` chaqiriladi va sahifa `GET /sync?after_id=` bilan uzilish paytida
// o'tkazib yuborilganlarni oladi.
//
// Mobil tarmoq va Telegram WebView'da ulanish tez-tez uziladi (ilova fonga o'tadi,
// tarmoq almashadi), shuning uchun:
//   * eksponensial kutish bilan qayta ulanish (1 s → 15 s);
//   * sahifa qayta ko'ringanda / tarmoq qaytganda — darhol;
//   * 4401 (token muddati tugadi) — tokenni yangilab qayta ulanish;
//   * har 25 s `ping` — proksi bo'sh ulanishni uzmasin, server "onlayn" deb bilsin
//     (onlayn bo'lsa Telegram bildirishnomasi yuborilmaydi).

export type ChatSocketEvent =
  | { type: 'message.new'; order_id: number; message: ChatMessage }
  | { type: 'message.edited'; order_id: number; message: ChatMessage }
  | { type: 'message.read'; order_id: number; user_id: number; last_read_message_id: number }
  | { type: 'typing'; order_id: number; user_id: number }
  | { type: 'conversation.updated'; order_id: number };

interface Options {
  onEvent: (event: ChatSocketEvent) => void;
  /** Har muvaffaqiyatli ulanishda (`reconnect=true` — birinchi emas). */
  onOpen?: (reconnect: boolean) => void;
  enabled?: boolean;
}

const PING_MS = 25_000;
const MAX_BACKOFF_MS = 15_000;
const TYPING_THROTTLE_MS = 3_000;

export function useChatSocket({ onEvent, onOpen, enabled = true }: Options) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const onEventRef = useRef(onEvent);
  const onOpenRef = useRef(onOpen);
  const lastTypingRef = useRef<Record<number, number>>({});

  useEffect(() => {
    onEventRef.current = onEvent;
    onOpenRef.current = onOpen;
  });

  useEffect(() => {
    if (!enabled) return;

    let stopped = false;
    let attempt = 0;
    let everOpened = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let pingTimer: ReturnType<typeof setInterval> | null = null;

    const clearTimers = () => {
      if (retryTimer) clearTimeout(retryTimer);
      if (pingTimer) clearInterval(pingTimer);
      retryTimer = null;
      pingTimer = null;
    };

    const scheduleReconnect = (delayMs?: number) => {
      if (stopped) return;
      clearTimers();
      const delay = delayMs ?? Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt);
      attempt += 1;
      retryTimer = setTimeout(connect, delay);
    };

    function connect() {
      if (stopped) return;
      const token = getAccessToken();
      if (!token) {
        scheduleReconnect();
        return;
      }
      const ws = new WebSocket(chatSocketUrl(token));
      wsRef.current = ws;

      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
        onOpenRef.current?.(everOpened);
        everOpened = true;
        pingTimer = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('{"type":"ping"}');
        }, PING_MS);
      };

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(String(e.data)) as { type?: string };
          if (data.type && data.type !== 'pong') onEventRef.current(data as ChatSocketEvent);
        } catch {
          // buzilgan kadr — e'tiborsiz
        }
      };

      ws.onclose = (e) => {
        if (wsRef.current === ws) wsRef.current = null;
        setConnected(false);
        clearTimers();
        if (stopped) return;
        if (e.code === 4401) {
          void refreshAccessToken().then(() => scheduleReconnect(300));
        } else {
          scheduleReconnect();
        }
      };
    }

    const wakeUp = () => {
      if (document.visibilityState !== 'visible') return;
      const ws = wsRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        attempt = 0;
        scheduleReconnect(0);
      }
    };

    connect();
    document.addEventListener('visibilitychange', wakeUp);
    window.addEventListener('online', wakeUp);

    return () => {
      stopped = true;
      clearTimers();
      document.removeEventListener('visibilitychange', wakeUp);
      window.removeEventListener('online', wakeUp);
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close(1000);
    };
  }, [enabled]);

  /** "yozmoqda…" — 3 s da ko'pi bilan bir marta yuboriladi. */
  const sendTyping = useCallback((orderId: number) => {
    const now = Date.now();
    if (now - (lastTypingRef.current[orderId] ?? 0) < TYPING_THROTTLE_MS) return;
    lastTypingRef.current[orderId] = now;
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'typing', order_id: orderId }));
  }, []);

  return { connected, sendTyping };
}
