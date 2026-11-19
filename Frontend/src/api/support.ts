// Support mikroservisi bilan ishlash — yordam chati.
//
// Har foydalanuvchiga BITTA chat (backend'da tarixiy nomi "ticket"): foydalanuvchi
// `/support/conversation...` yo'llari bilan o'z chatida ishlaydi, xodim esa barcha
// chatlarni `/support/tickets/...` orqali ko'radi.
//
// Bu xizmat asosiy backenddan ALOHIDA: o'z konteyneri, o'z bazasi (`support_db`) va o'z
// prefiksi (`/support`, `/api` ostida emas). Shuning uchun `api` emas, `supportApi`
// wrapper'i ishlatiladi — u faqat bazasi bilan farq qiladi, token va 401→refresh mantiqi
// bir xil (support ham xuddi shu access tokenni umumiy SECRET_KEY bilan tekshiradi).
//
// Real vaqt: `/support/ws` — bitta umumiy WebSocket (`subscribeSupportEvents`), uni
// bir nechta komponent baham ko'radi. Uzilsa eksponensial kechikish bilan qayta ulanadi;
// qayta ulanganda tinglovchilarga `resync` keladi — o'tkazib yuborilgan hodisalar
// bo'lishi mumkin, ekran ma'lumotini qayta so'rab olsin.
// Matnli xabar ham shu WS orqali yuboriladi (`sendSupportMessage`); ulanish yo'q yoki
// javob kelmasa — o'sha `client_id` bilan REST (server takrorni yozmaydi).

import { useEffect, useRef } from 'react';
import { ApiError, getAccessToken, supportApi } from './client';
import type {
  SupportConversationResponse,
  SupportSocketEvent,
  SupportUnreadSummary,
  TicketDetail,
  TicketListItem,
  TicketMessageCreated,
  TicketMessagePage,
  TicketPage,
  TicketPublic,
  TicketStatus,
} from '../types/api';

// client.ts dagi bilan bir xil manba: bo'sh — frontend bilan bir origin (proxy orqali).
const SUPPORT_BASE_URL = ((import.meta.env.VITE_SUPPORT_BASE_URL as string | undefined) ?? '').replace(
  /\/$/,
  '',
);

/** Support yo'lini to'liq URL'ga aylantiradi (fayl havolalari va WS uchun). */
export function supportUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return new URL(`${SUPPORT_BASE_URL}${path}`, window.location.origin).toString();
}

// ─── REST ────────────────────────────────────────────────────────────────────

export interface ListTicketsParams {
  status?: TicketStatus;
  order_id?: number;
  /** Xodim uchun: hammasi emas, faqat o'z murojaatlarini ko'rsatish.
   *  Oddiy foydalanuvchida ta'siri yo'q — u baribir faqat o'zinikini ko'radi. */
  mine?: boolean;
  /** Xodim uchun: `me` — menga biriktirilgan, `none` — hech kimga biriktirilmagan. */
  assigned?: 'me' | 'none';
  limit?: number;
  offset?: number;
}

export function listTickets(params: ListTicketsParams = {}): Promise<TicketPage> {
  return supportApi.get<TicketPage>('/support/tickets', {
    status: params.status,
    order_id: params.order_id,
    mine: params.mine,
    assigned: params.assigned,
    limit: params.limit,
    offset: params.offset,
  });
}

/** Ochish o'qildi deb belgilaydi (server tomonda). */
export function getTicket(ticketId: number, messagesLimit = 50): Promise<TicketDetail> {
  return supportApi.get<TicketDetail>(`/support/tickets/${ticketId}`, { messages_limit: messagesLimit });
}

export function listTicketMessages(
  ticketId: number,
  beforeId: number,
  limit = 50,
): Promise<TicketMessagePage> {
  return supportApi.get<TicketMessagePage>(`/support/tickets/${ticketId}/messages`, {
    before_id: beforeId,
    limit,
  });
}

// ─── O'z chatim ──────────────────────────────────────────────────────────────

/** O'z chatim (oxirgi xabarlar bilan); hali yozmagan bo'lsam `conversation: null`.
 *  Ochish o'qildi deb belgilaydi. */
export function getConversation(messagesLimit = 50): Promise<SupportConversationResponse> {
  return supportApi.get<SupportConversationResponse>('/support/conversation', { messages_limit: messagesLimit });
}

export function listConversationMessages(beforeId: number, limit = 50): Promise<TicketMessagePage> {
  return supportApi.get<TicketMessagePage>('/support/conversation/messages', { before_id: beforeId, limit });
}

export function markConversationRead(): Promise<void> {
  return supportApi.post<void>('/support/conversation/read');
}

export function markTicketRead(ticketId: number): Promise<void> {
  return supportApi.post<void>(`/support/tickets/${ticketId}/read`);
}

export function getUnreadSummary(asStaff = false): Promise<SupportUnreadSummary> {
  return supportApi.get<SupportUnreadSummary>('/support/unread', asStaff ? { as_staff: true } : undefined);
}

/** Faqat xodim — `allowed_statuses` bo'yicha (chat yopilmaydi). */
export function updateTicketStatus(ticketId: number, status: TicketStatus): Promise<TicketListItem> {
  return supportApi.patch<TicketListItem>(`/support/tickets/${ticketId}/status`, { status });
}

export function assignTicketToMe(ticketId: number): Promise<TicketListItem> {
  return supportApi.post<TicketListItem>(`/support/tickets/${ticketId}/assign`);
}

export function unassignTicket(ticketId: number): Promise<TicketListItem> {
  return supportApi.delete<TicketListItem>(`/support/tickets/${ticketId}/assign`);
}

/** Rasm/video/hujjat yuborish (multipart). Fayl turi serverda BAYTLARDAN tekshiriladi.
 *  `ticketId` yo'q — o'z chatimga (birinchi xabar bo'lsa chat yaratiladi). */
export async function uploadSupportAttachment(
  { ticketId, file, body = '', orderId }: { ticketId?: number; file: File; body?: string; orderId?: number | null },
  allowRetry = true,
): Promise<TicketMessageCreated> {
  const form = new FormData();
  form.append('file', file);
  form.append('body', body);
  if (ticketId == null && orderId != null) form.append('order_id', String(orderId));
  const token = getAccessToken();
  const path = ticketId != null ? `/support/tickets/${ticketId}/attachments` : '/support/conversation/attachments';
  const res = await fetch(supportUrl(path), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (res.status === 401 && allowRetry) {
    // Token eskirgan: oddiy so'rov orqali umumiy refresh mantiqini ishga tushiramiz.
    await supportApi.get('/support/unread').catch(() => undefined);
    return uploadSupportAttachment({ ticketId, file, body, orderId }, false);
  }
  if (!res.ok) {
    let detail: unknown = null;
    try {
      detail = await res.json();
    } catch {
      if (res.status === 413) detail = { detail: 'Fayl juda katta' };
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as TicketMessageCreated;
}

// ─── Real vaqt ───────────────────────────────────────────────────────────────

/** Tinglovchilarga boradigan hodisalar (yuborish javoblari — `sendSupportMessage` ichida). */
export type SupportLiveEvent =
  | Exclude<SupportSocketEvent, { type: 'message.ack' } | { type: 'message.error' }>
  | { type: 'resync' };
type Listener = (event: SupportLiveEvent) => void;

const listeners = new Set<Listener>();
let socket: WebSocket | null = null;
// `hello` kelgandan keyingina server xabar qabul qiladi (token tekshirilgan).
let socketReady = false;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let pingTimer: ReturnType<typeof setInterval> | undefined;
let attempt = 0;
let connectedOnce = false;

/** WS orqali yuborilib javobi kutilayotgan xabarlar (`client_id` → kutuvchi). */
interface PendingSend {
  resolve: (message: TicketMessageCreated) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}
const pendingSends = new Map<string, PendingSend>();
/** Shuncha vaqtda `message.ack` kelmasa — REST bilan (o'sha `client_id`) qayta yuboriladi. */
const WS_SEND_TIMEOUT_MS = 6_000;

class WsSendFailed extends Error {}

function failPendingSends(): void {
  for (const [id, pending] of pendingSends) {
    clearTimeout(pending.timer);
    pending.reject(new WsSendFailed('WS uzildi'));
    pendingSends.delete(id);
  }
}

function emit(event: SupportLiveEvent): void {
  for (const listener of [...listeners]) {
    try {
      listener(event);
    } catch (err) {
      console.error('Support WS tinglovchisida xato', err);
    }
  }
}

function scheduleReconnect(): void {
  clearTimeout(retryTimer);
  if (!listeners.size) return;
  const delay = Math.min(30_000, 1_000 * 2 ** attempt) + Math.random() * 500;
  attempt += 1;
  retryTimer = setTimeout(() => {
    if (listeners.size && !socket) connect();
  }, delay);
}

function connect(): void {
  const token = getAccessToken();
  if (!token) {
    scheduleReconnect();
    return;
  }
  const url = new URL(supportUrl('/support/ws'));
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('token', token);

  const ws = new WebSocket(url.toString());
  socket = ws;
  socketReady = false;

  ws.onopen = () => {
    clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 30_000);
  };
  ws.onmessage = (msg) => {
    let event: SupportSocketEvent;
    try {
      event = JSON.parse(String(msg.data)) as SupportSocketEvent;
    } catch {
      return;
    }
    if (event.type === 'ping') return;
    if (event.type === 'hello') {
      attempt = 0;
      socketReady = true;
      if (connectedOnce) emit({ type: 'resync' });
      connectedOnce = true;
      return;
    }
    if (event.type === 'message.ack' || event.type === 'message.error') {
      const pending = pendingSends.get(event.client_id);
      if (!pending) return;
      pendingSends.delete(event.client_id);
      clearTimeout(pending.timer);
      if (event.type === 'message.ack') pending.resolve(event.message);
      else pending.reject(new ApiError(event.status, { detail: event.detail }));
      return;
    }
    emit(event);
  };
  ws.onclose = (ev) => {
    clearInterval(pingTimer);
    if (socket === ws) {
      socket = null;
      socketReady = false;
    }
    failPendingSends();
    if (!listeners.size || ev.code === 4403) return; // bloklangan — qayta urinmaymiz
    if (ev.code === 4401) {
      // Token muddati o'tgan: oddiy so'rov refresh'ni ishga tushiradi, keyin qayta ulanamiz.
      void supportApi
        .get('/support/unread')
        .catch(() => undefined)
        .finally(scheduleReconnect);
      return;
    }
    scheduleReconnect();
  };
}

/** Support hodisalariga obuna. Qaytgan funksiya obunani bekor qiladi. */
export function subscribeSupportEvents(listener: Listener): () => void {
  listeners.add(listener);
  if (!socket) connect();
  return () => {
    listeners.delete(listener);
    if (!listeners.size) {
      clearTimeout(retryTimer);
      clearInterval(pingTimer);
      socket?.close();
      socket = null;
      socketReady = false;
      failPendingSends();
      connectedOnce = false;
      attempt = 0;
    }
  };
}

function newClientId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export interface SendSupportMessageInput {
  body: string;
  /** Xodim boshqa odamning chatiga yozganda; bo'lmasa — o'z chatim. */
  ticketId?: number;
  /** Xabar qaysi buyurtma haqida (faqat o'z chatimda). */
  orderId?: number | null;
}

/** Matnli xabar yuborish: WebSocket orqali (`message.send` → `message.ack`).
 *  Ulanish yo'q, uzildi yoki javob kechikdi — o'sha `client_id` bilan REST orqali:
 *  server takrorni yozmaydi, shuning uchun xabar ikki marta tushmaydi.
 *  Server rad etsa (`message.error`) — `ApiError` (REST bilan qayta urinilmaydi). */
export async function sendSupportMessage(input: SendSupportMessageInput): Promise<TicketMessageCreated> {
  const clientId = newClientId();
  const payload = {
    body: input.body,
    order_id: input.ticketId == null ? (input.orderId ?? null) : null,
    client_id: clientId,
  };
  const ws = socket;
  if (ws && socketReady && ws.readyState === WebSocket.OPEN) {
    try {
      return await new Promise<TicketMessageCreated>((resolve, reject) => {
        const timer = setTimeout(() => {
          pendingSends.delete(clientId);
          reject(new WsSendFailed('WS javobi kelmadi'));
        }, WS_SEND_TIMEOUT_MS);
        pendingSends.set(clientId, { resolve, reject, timer });
        ws.send(JSON.stringify({ type: 'message.send', ticket_id: input.ticketId ?? null, ...payload }));
      });
    } catch (err) {
      if (!(err instanceof WsSendFailed)) throw err;
      // WS ishlamadi — pastda REST bilan.
    }
  }
  return input.ticketId != null
    ? supportApi.post<TicketMessageCreated>(`/support/tickets/${input.ticketId}/messages`, payload)
    : supportApi.post<TicketMessageCreated>('/support/conversation/messages', payload);
}

/** React uchun: komponent yashaguncha hodisalarni tinglaydi (eng so'nggi handler bilan). */
export function useSupportEvents(handler: Listener, enabled = true): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    if (!enabled) return undefined;
    return subscribeSupportEvents((event) => ref.current(event));
  }, [enabled]);
}

/** WS'dan kelgan qisqa ko'rinishni ro'yxat elementiga qo'shadi (unread/allowed saqlanadi). */
export function mergeTicket<T extends TicketListItem>(current: T, update: TicketPublic): T {
  return { ...current, ...update, unread_count: current.unread_count, allowed_statuses: current.allowed_statuses };
}

// ─── Ko'rinish yordamchilari ─────────────────────────────────────────────────

/** Holat nomlarining o'zbekcha ko'rinishi (xodim paneli). `closed` — eski yozuvlar uchun. */
export const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  open: 'Yangi',
  in_progress: 'Ko’rib chiqilmoqda',
  resolved: 'Hal qilindi',
  closed: 'Hal qilindi',
};

/** Xodim tanlay oladigan holatlar (chat yopilmaydi — support_service/rules.py). */
export const ACTIVE_TICKET_STATUSES: TicketStatus[] = ['open', 'in_progress', 'resolved'];

export const TICKET_PRIORITY_LABELS: Record<string, string> = {
  low: 'Past',
  normal: 'Oddiy',
  high: 'Yuqori',
  urgent: 'Shoshilinch',
};

export const SUPPORT_ROLE_LABELS: Record<string, string> = {
  sender: 'mijoz',
  driver: 'haydovchi',
  admin: 'admin',
  manager: 'menejer',
};

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** Fayl tanlash oynasi uchun — server qabul qiladigan turlar (support_service/mime.py). */
export const ATTACHMENT_ACCEPT =
  'image/jpeg,image/png,image/webp,image/gif,image/heic,video/mp4,video/quicktime,video/webm,application/pdf,.doc,.docx,.xls,.xlsx,.pptx';

/** Oxirgi xabarning qisqa matni (ro'yxat kartochkasi uchun). */
export function previewText(item: TicketListItem): string {
  const last = item.last_message;
  if (!last) return '';
  const text = last.body.trim() || (last.has_attachments ? '📎 Biriktirma' : '');
  return last.has_attachments && last.body.trim() ? `📎 ${text}` : text;
}
