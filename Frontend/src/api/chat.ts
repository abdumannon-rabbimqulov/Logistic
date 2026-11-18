// Buyurtma chati — `chat_service/` mikroservisi (prefiks `/chat`, `/api` ostida EMAS).
//
// Suhbat buyurtma raqami bilan topiladi: `/chat/orders/{orderId}/...`. Kirish faqat
// buyurtmaning ikki ishtirokchisiga (yuk egasi va biriktirilgan haydovchi); begona
// yoki hali ochilmagan chat uchun 404 qaytadi.
//
// Media ikki bosqichda yuboriladi: (1) `uploadChatMedia` — XHR bilan, progress
// ko'rsatish uchun; (2) `sendChatMessage({ kind, media_id })`. Fayl URL'lari
// imzolangan va muddatli — `<img src>` to'g'ridan-to'g'ri ishlatiladi, token kerak emas.

import { chatApi, chatBaseUrl, getAccessToken, refreshAccessToken, ApiError } from './client';

export type ChatMessageKind = 'text' | 'photo' | 'video' | 'voice' | 'document' | 'location';
export type ChatMediaKind = 'photo' | 'video' | 'voice' | 'document';

export interface ChatMedia {
  id: string;
  kind: ChatMediaKind;
  mime: string;
  size_bytes: number;
  url: string;
  thumb_url: string | null;
  width: number | null;
  height: number | null;
  duration_s: number | null;
  name: string | null;
}

export interface ChatReplyRef {
  id: number;
  sender_user_id: number;
  kind: ChatMessageKind;
  preview: string;
  deleted: boolean;
}

export interface ChatMessage {
  id: number;
  order_id: number;
  sender_user_id: number;
  kind: ChatMessageKind;
  text: string | null;
  media: ChatMedia | null;
  duration_s: number | null;
  lat: number | null;
  lon: number | null;
  reply_to: ChatReplyRef | null;
  client_id: string | null;
  created_at: string;
  edited_at: string | null;
  deleted_at: string | null;
}

export interface ChatConversation {
  id: number;
  order_id: number;
  status: 'open' | 'readonly';
  /** Yozib bo'lmasa — sabab (chat yopilgan yoki buyurtmada haydovchi yo'q). */
  write_blocked_reason: string | null;
  readonly_at: string | null;
  order_status: string | null;
  my_role: 'sender' | 'driver';
  peer_user_id: number | null;
  my_last_read_id: number;
  /** ✓✓: sherigim shu id gacha o'qigan. */
  peer_last_read_id: number;
  unread_count: number;
  last_message_at: string | null;
  last_message?: ChatMessage | null;
}

export interface ChatPage {
  messages: ChatMessage[];
  has_more: boolean;
}

export interface ChatSync extends ChatPage {
  changed: ChatMessage[];
  conversation: ChatConversation;
  server_time: string;
}

export interface SendMessageInput {
  kind: ChatMessageKind;
  text?: string | null;
  media_id?: string;
  lat?: number;
  lon?: number;
  reply_to_id?: number | null;
  client_id?: string;
}

const base = (orderId: number) => `/chat/orders/${orderId}`;

export function getChatConversation(orderId: number): Promise<ChatConversation> {
  return chatApi.get<ChatConversation>(base(orderId));
}

export function listChatConversations(): Promise<ChatConversation[]> {
  return chatApi.get<ChatConversation[]>('/chat/conversations');
}

export function getChatUnread(orderId: number): Promise<{ order_id: number; unread_count: number; status: string }> {
  return chatApi.get(`${base(orderId)}/unread`);
}

export function getChatMessages(
  orderId: number,
  params: { before_id?: number; after_id?: number; limit?: number } = {},
): Promise<ChatPage> {
  return chatApi.get<ChatPage>(`${base(orderId)}/messages`, params);
}

/** Qayta ulanishda: `afterId` dan keyingi yangi va `since` dan beri o'zgarganlar. */
export function syncChat(orderId: number, afterId: number, since?: string | null): Promise<ChatSync> {
  return chatApi.get<ChatSync>(`${base(orderId)}/sync`, { after_id: afterId, since: since ?? undefined });
}

export function sendChatMessage(orderId: number, input: SendMessageInput): Promise<ChatMessage> {
  return chatApi.post<ChatMessage>(`${base(orderId)}/messages`, input);
}

export function editChatMessage(orderId: number, messageId: number, text: string): Promise<ChatMessage> {
  return chatApi.patch<ChatMessage>(`${base(orderId)}/messages/${messageId}`, { text });
}

export function deleteChatMessage(orderId: number, messageId: number): Promise<ChatMessage> {
  return chatApi.delete<ChatMessage>(`${base(orderId)}/messages/${messageId}`);
}

export function markChatRead(
  orderId: number,
  lastReadMessageId: number,
): Promise<{ order_id: number; last_read_message_id: number; unread_count: number }> {
  return chatApi.post(`${base(orderId)}/read`, { last_read_message_id: lastReadMessageId });
}

export interface UploadInput {
  kind: ChatMediaKind;
  file: Blob;
  fileName: string;
  durationS?: number;
  /** Video uchun poster kadr (JPEG) — server thumbnail qiladi. */
  thumb?: Blob | null;
}

export interface UploadHandle {
  promise: Promise<ChatMedia>;
  abort: () => void;
}

/** Faylni XHR bilan yuklaydi (`fetch` yuklash progressini bermaydi). 401 bo'lsa
 *  tokenni bir marta yangilab qayta urinadi. */
export function uploadChatMedia(
  orderId: number,
  input: UploadInput,
  onProgress?: (fraction: number) => void,
): UploadHandle {
  let xhr: XMLHttpRequest | null = null;
  let aborted = false;

  const attempt = (retry: boolean): Promise<ChatMedia> =>
    new Promise<ChatMedia>((resolve, reject) => {
      const form = new FormData();
      form.append('kind', input.kind);
      form.append('file', input.file, input.fileName);
      if (input.durationS != null) form.append('duration_s', input.durationS.toFixed(1));
      if (input.thumb) form.append('thumb', input.thumb, 'thumb.jpg');

      xhr = new XMLHttpRequest();
      xhr.open('POST', `${chatBaseUrl()}${base(orderId)}/media`);
      const token = getAccessToken();
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress?.(e.loaded / e.total);
      };
      xhr.onerror = () => reject(new ApiError(0, { detail: "Tarmoq xatosi — fayl yuklanmadi" }));
      xhr.onabort = () => reject(new ApiError(0, { detail: 'Bekor qilindi' }));
      xhr.onload = () => {
        const status = xhr!.status;
        let body: unknown = null;
        try {
          body = JSON.parse(xhr!.responseText);
        } catch {
          body = null;
        }
        if (status === 401 && retry) {
          void refreshAccessToken().then((ok) =>
            ok && !aborted ? attempt(false).then(resolve, reject) : reject(new ApiError(401, body)),
          );
          return;
        }
        if (status >= 200 && status < 300) resolve(body as ChatMedia);
        else reject(new ApiError(status, body));
      };
      xhr.send(form);
    });

  return {
    promise: attempt(true),
    abort: () => {
      aborted = true;
      xhr?.abort();
    },
  };
}

/** WebSocket manzili (nisbiy baza bo'lsa joriy origin'dan, http→ws). */
export function chatSocketUrl(token: string): string {
  const raw = `${chatBaseUrl()}/chat/ws`;
  const url = new URL(raw, window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('token', token);
  return url.toString();
}

export const CHAT_LIMITS = {
  videoBytes: 50 * 1024 * 1024,
  photoBytes: 10 * 1024 * 1024,
  documentBytes: 20 * 1024 * 1024,
  voiceSeconds: 5 * 60,
} as const;
