// Support mikroservisi bilan ishlash (murojaatlar / ticketlar).
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

import { useEffect, useRef } from 'react';
import { ApiError, getAccessToken, supportApi } from './client';
import type {
  SupportSocketEvent,
  SupportUnreadSummary,
  TicketCreateInput,
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

export function createTicket(data: TicketCreateInput): Promise<TicketDetail> {
  return supportApi.post<TicketDetail>('/support/tickets', data);
}

/** Yopilgan murojaatga javob yozib bo'lmaydi — backend 409 qaytaradi. Javobda yangi xabar
 *  va murojaatning yangilangan holati (`ticket`) bor. */
export function replyToTicket(ticketId: number, body: string): Promise<TicketMessageCreated> {
  return supportApi.post<TicketMessageCreated>(`/support/tickets/${ticketId}/messages`, { body });
}

export function markTicketRead(ticketId: number): Promise<void> {
  return supportApi.post<void>(`/support/tickets/${ticketId}/read`);
}

export function getUnreadSummary(asStaff = false): Promise<SupportUnreadSummary> {
  return supportApi.get<SupportUnreadSummary>('/support/unread', asStaff ? { as_staff: true } : undefined);
}

/** Xodim — `allowed_statuses` bo'yicha; murojaat egasi — faqat `closed`. */
export function updateTicketStatus(ticketId: number, status: TicketStatus): Promise<TicketListItem> {
  return supportApi.patch<TicketListItem>(`/support/tickets/${ticketId}/status`, { status });
}

export function assignTicketToMe(ticketId: number): Promise<TicketListItem> {
  return supportApi.post<TicketListItem>(`/support/tickets/${ticketId}/assign`);
}

export function unassignTicket(ticketId: number): Promise<TicketListItem> {
  return supportApi.delete<TicketListItem>(`/support/tickets/${ticketId}/assign`);
}

/** Rasm/video/hujjat yuborish (multipart). Fayl turi serverda BAYTLARDAN tekshiriladi. */
export async function uploadTicketAttachment(
  ticketId: number,
  file: File,
  body = '',
  allowRetry = true,
): Promise<TicketMessageCreated> {
  const form = new FormData();
  form.append('file', file);
  form.append('body', body);
  const token = getAccessToken();
  const res = await fetch(supportUrl(`/support/tickets/${ticketId}/attachments`), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: form,
  });
  if (res.status === 401 && allowRetry) {
    // Token eskirgan: oddiy so'rov orqali umumiy refresh mantiqini ishga tushiramiz.
    await supportApi.get('/support/unread').catch(() => undefined);
    return uploadTicketAttachment(ticketId, file, body, false);
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

export type SupportLiveEvent = SupportSocketEvent | { type: 'resync' };
type Listener = (event: SupportLiveEvent) => void;

const listeners = new Set<Listener>();
let socket: WebSocket | null = null;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let pingTimer: ReturnType<typeof setInterval> | undefined;
let attempt = 0;
let connectedOnce = false;

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
      if (connectedOnce) emit({ type: 'resync' });
      connectedOnce = true;
      return;
    }
    emit(event);
  };
  ws.onclose = (ev) => {
    clearInterval(pingTimer);
    if (socket === ws) socket = null;
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
      connectedOnce = false;
      attempt = 0;
    }
  };
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

/** Holat nomlarining o'zbekcha ko'rinishi — ro'yxat va tafsilot ekranlarida bir xil. */
export const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  open: 'Ochiq',
  in_progress: 'Ko’rib chiqilmoqda',
  resolved: 'Hal qilindi',
  closed: 'Yopilgan',
};

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

/** Yopilgan/hal qilingan murojaatga yangi xabar yozilmaydi (support_service/models.py). */
export function isTicketClosed(status: TicketStatus): boolean {
  return status === 'closed' || status === 'resolved';
}

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
