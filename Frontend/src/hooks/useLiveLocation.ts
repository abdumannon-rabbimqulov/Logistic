import { useEffect, useRef, useState } from 'react';
import { wsUrl } from '../api/client';
import {
  TelegramLocationError,
  getTelegramLocationOnce,
  isTelegramLocationSupported,
} from '../utils/telegramLocation';

export interface LiveCoords {
  latitude: number;
  longitude: number;
  accuracy: number | null;
  /** GPS nuqtasi olingan vaqt (epoch ms). */
  at: number;
}

/** Joylashuv nima sababdan yo'qoldi — serverga ham shu yuboriladi. */
export type GpsLostReason = 'denied' | 'unavailable' | 'timeout';

interface Options {
  /** Liniyaga chiqqanda `true` — koordinata backendga (WS) ham yuboriladi. */
  broadcast?: boolean;
}

/**
 * Backendga yuborish oralig'i. Xaritadagi ko'k nuqta har bir GPS o'zgarishida
 * darhol yangilanadi, serverga esa 30 soniyada bir marta yuboriladi — mobil
 * trafik va Redis yozuvlarini tejaydi.
 */
const BROADCAST_INTERVAL_MS = 30_000;

/** Telegram `LocationManager`da `watchPosition` yo'q — shu oraliqda `getLocation()`
 *  qayta so'raladi. Xaritadagi nuqta shuncha tez-tez yangilanadi. */
const TELEGRAM_POLL_INTERVAL_MS = 8_000;

/** Shuncha vaqt yangi GPS nuqtasi kelmasa — joylashuv "jim" (o'chgan) hisoblanadi. */
const GPS_SILENCE_MS = 60_000;

/** WS qayta ulanish: 2s, 4s, 8s ... 30s gacha. */
const RECONNECT_MIN_MS = 2_000;
const RECONNECT_MAX_MS = 30_000;

interface LiveLocationState {
  coords: LiveCoords | null;
  error: string | null;
  /** Birinchi koordinata hali kelmagan holat (xaritada "aniqlanmoqda" ko'rsatish uchun). */
  loading: boolean;
  /** Joylashuv yo'qolgan (ruxsat yo'q, GPS o'chgan yoki 60 s dan beri jim). */
  gpsLost: GpsLostReason | null;
  /** Telegram sozlamalarini ochish tugmasini ko'rsatish mumkinmi. */
  canOpenSettings: boolean;
}

/** `/drivers/ws/location` manzilini quradi (client.ts dagi `driverLocationsWsUrl` naqshi). */
function locationWsUrl(): string {
  return wsUrl('/drivers/ws/location');
}

/**
 * Haydovchining jonli joylashuvi va (broadcast=true bo'lsa) uni
 * `/drivers/ws/location` WebSocket'iga yuborish — admin/sender jonli xaritasi
 * aynan shu ma'lumotdan oziqlanadi (services/live_location.py).
 *
 * Joylashuv manbai: Telegram ichida `LocationManager` ustuvor (`utils/telegramLocation.ts`),
 * Telegramdan tashqarida `watchPosition`.
 *
 * Joylashuv yo'qolsa (xato yoki 60 s jimlik) oxirgi nuqta UNUTILADI va serverga
 * qayta yuborilmaydi — ilgari eski nuqta har 30 s da "yangi" bo'lib ketardi va
 * haydovchi GPS o'chgan holda ham joyida turgandek ko'rinardi. Buning o'rniga
 * serverga `{event: "gps_lost"}` yuboriladi va u haydovchi/sender/adminni ogohlantiradi.
 *
 * Liniyadan chiqilganda WS'ga `{event: "stop"}` yuboriladi, shunda haydovchi admin
 * xaritasidan olib tashlanadi. Ulanish uzilsa avtomatik qayta ulanadi.
 */
export function useLiveLocation({ broadcast = false }: Options = {}): LiveLocationState {
  const [coords, setCoords] = useState<LiveCoords | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [gpsLost, setGpsLost] = useState<GpsLostReason | null>(null);
  const [canOpenSettings, setCanOpenSettings] = useState(false);
  const [socketGen, setSocketGen] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  // Oxirgi olingan koordinata — interval taymeri shu qiymatni yuboradi.
  const latestCoordsRef = useRef<LiveCoords | null>(null);
  const gpsLostRef = useRef<GpsLostReason | null>(null);
  // Shu yo'qolish haqida serverga xabar berildimi (har yo'qolishga bir marta).
  const lostReportedRef = useRef(false);

  const reportLost = () => {
    const socket = socketRef.current;
    const reason = gpsLostRef.current;
    if (!socket || !reason || lostReportedRef.current) return;
    if (socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ event: 'gps_lost', reason }));
    lostReportedRef.current = true;
  };

  // 1) Joylashuvni kuzatish (Telegram LocationManager yoki brauzer watchPosition).
  useEffect(() => {
    let cancelled = false;

    const applyCoords = (next: LiveCoords) => {
      if (cancelled) return;
      latestCoordsRef.current = next;
      gpsLostRef.current = null;
      lostReportedRef.current = false;
      setCoords(next);
      setError(null);
      setGpsLost(null);
      setCanOpenSettings(false);
      setLoading(false);
    };

    const markLost = (reason: GpsLostReason, message: string, settings = false) => {
      if (cancelled) return;
      // Eski nuqta endi "jonli" emas — serverga qayta yuborilmasin.
      latestCoordsRef.current = null;
      if (gpsLostRef.current !== reason) lostReportedRef.current = false;
      gpsLostRef.current = reason;
      setGpsLost(reason);
      setError(message);
      setCanOpenSettings(settings);
      setLoading(false);
      reportLost();
    };

    // Jimlikni aniqlash: GPS xato bermasdan shunchaki to'xtab qolishi ham mumkin.
    const silenceTimer = window.setInterval(() => {
      const last = latestCoordsRef.current;
      if (last && Date.now() - last.at > GPS_SILENCE_MS) {
        markLost('timeout', "Joylashuv 1 daqiqadan beri yangilanmayapti. GPS yoqilganini tekshiring.");
      }
    }, 10_000);

    if (isTelegramLocationSupported()) {
      const poll = () => {
        getTelegramLocationOnce()
          .then((sample) => applyCoords({ ...sample, at: Date.now() }))
          .catch((err: unknown) => {
            const settings = err instanceof TelegramLocationError && err.canOpenSettings;
            markLost(
              settings ? 'denied' : 'unavailable',
              err instanceof Error ? err.message : 'Joylashuv aniqlanmadi',
              settings,
            );
          });
      };
      poll();
      const id = window.setInterval(poll, TELEGRAM_POLL_INTERVAL_MS);
      return () => {
        cancelled = true;
        window.clearInterval(id);
        window.clearInterval(silenceTimer);
      };
    }

    if (!navigator.geolocation) {
      markLost('unavailable', "Qurilma geolokatsiyani qo'llab-quvvatlamaydi");
      return () => {
        cancelled = true;
        window.clearInterval(silenceTimer);
      };
    }

    const watchId = navigator.geolocation.watchPosition(
      (pos) => {
        applyCoords({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          accuracy: pos.coords.accuracy ?? null,
          at: pos.timestamp || Date.now(),
        });
      },
      (err) => {
        if (err.code === err.PERMISSION_DENIED) {
          markLost('denied', "Joylashuvga ruxsat berilmagan — brauzer sozlamalaridan ruxsat bering");
        } else if (err.code === err.POSITION_UNAVAILABLE) {
          markLost('unavailable', "GPS o'chirilgan yoki signal yo'q");
        } else if (!latestCoordsRef.current) {
          // TIMEOUT: nuqta umuman kelmagan bo'lsa — xato; aks holda jimlik taymeri hal qiladi.
          markLost('timeout', 'Joylashuv aniqlanmadi');
        }
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 },
    );

    return () => {
      cancelled = true;
      window.clearInterval(silenceTimer);
      navigator.geolocation.clearWatch(watchId);
    };
    // reportLost faqat ref'larni o'qiydi — qayta ishga tushirish shart emas.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 2) Liniyadagi holatda — WS ulanishi (uzilsa backoff bilan qayta ulanadi).
  useEffect(() => {
    if (!broadcast) return;

    let closedByUs = false;
    let attempt = 0;
    let reconnectTimer: number | undefined;
    let socket: WebSocket | null = null;

    const connect = () => {
      try {
        socket = new WebSocket(locationWsUrl());
      } catch {
        scheduleReconnect();
        return;
      }
      socketRef.current = socket;
      socket.addEventListener('open', () => {
        attempt = 0;
        // Yangi ulanishda joriy holat qayta bildiriladi (server oldingi ulanishni bilmaydi).
        lostReportedRef.current = false;
        reportLost();
        setSocketGen((g) => g + 1);
      });
      socket.addEventListener('close', () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (!closedByUs) scheduleReconnect();
      });
    };

    const scheduleReconnect = () => {
      if (closedByUs) return;
      const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_MIN_MS * 2 ** attempt);
      attempt += 1;
      reconnectTimer = window.setTimeout(connect, delay);
    };

    connect();

    return () => {
      closedByUs = true;
      window.clearTimeout(reconnectTimer);
      socketRef.current = null;
      try {
        if (socket && socket.readyState === WebSocket.OPEN) {
          // Liniyadan chiqdik — admin xaritasidan ham olib tashlansin
          socket.send(JSON.stringify({ event: 'stop' }));
        }
        socket?.close();
      } catch {
        // ulanish allaqachon yopilgan
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [broadcast]);

  // 3) Koordinatani backendga har 30 soniyada yuborish.
  const hasCoords = coords !== null;
  useEffect(() => {
    if (!broadcast) return;

    const send = () => {
      const socket = socketRef.current;
      const point = latestCoordsRef.current;
      if (!socket || !point) return;
      if (socket.readyState !== WebSocket.OPEN) return;

      // `timestamp` — nuqta olingan vaqt: server eski nuqtani "jonli" deb qabul qilmaydi.
      // `accuracy` — geofence zaxira koordinatasida radiusni kengaytirish uchun.
      socket.send(
        JSON.stringify({
          latitude: point.latitude,
          longitude: point.longitude,
          timestamp: point.at,
          ...(point.accuracy != null ? { accuracy: point.accuracy } : {}),
        }),
      );
    };

    // Birinchi koordinata yoki yangi ulanish bo'lishi bilan darhol yuboriladi, keyin interval.
    send();
    const timer = window.setInterval(send, BROADCAST_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [broadcast, hasCoords, socketGen]);

  return { coords, error, loading, gpsLost, canOpenSettings };
}
