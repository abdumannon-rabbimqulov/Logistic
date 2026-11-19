import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ChangeEvent, KeyboardEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import {
  ATTACHMENT_ACCEPT,
  SUPPORT_ROLE_LABELS,
  formatFileSize,
  getConversation,
  listConversationMessages,
  markConversationRead,
  mergeTicket,
  sendSupportMessage,
  supportUrl,
  uploadSupportAttachment,
  useSupportEvents,
} from '../api/support';
import { useAuth } from '../auth/AuthProvider';
import type { TicketAttachment, TicketDetail, TicketMessage, TicketMessageCreated } from '../types/api';
import styles from './SupportChatPage.module.css';
import { formatShortDateTime } from '../utils/format';

// Yordam xizmati — foydalanuvchining YAGONA chati (sender ham, haydovchi ham).
// Har muammo uchun alohida murojaat ochilmaydi: barcha savollar shu chatda, tarix bilan.
// Chat birinchi xabar bilan yaratiladi (`conversation: null` — hali yozilmagan).
//
// Real vaqt: xodim javoblari `/support/ws` orqali keladi; matnli xabar ham WS orqali
// yuboriladi (`sendSupportMessage`, javob kelmasa REST bilan, takrorlanmaydi).
// Buyurtma sahifasidan "Muammo bormi?" bilan kelinsa — keyingi xabar shu buyurtmaga
// bog'lanadi (`orderId`), xodim uni ko'radi.

/** Buyurtma sahifasidan kelinganda: keyingi xabar shu buyurtma haqida. */
export interface SupportChatNavState {
  orderId?: number;
}

const COMPOSER_MAX_HEIGHT = 140;

/** WS javobi kutilayotgan yoki yuborilmagan matnli xabar (ro'yxat oxirida ko'rsatiladi). */
interface PendingMessage {
  key: number;
  body: string;
  orderId: number | null;
  failed: string | null;
}

function appendUnique(list: TicketMessage[], message: TicketMessage): TicketMessage[] {
  return list.some((m) => m.id === message.id) ? list : [...list, message];
}

function stripTicket(created: TicketMessageCreated): TicketMessage {
  const { ticket: _ticket, ...message } = created;
  return message;
}

function PaperclipIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M21 11.5l-8.6 8.6a5.5 5.5 0 01-7.8-7.8l8.6-8.6a3.7 3.7 0 015.2 5.2l-8.6 8.6a1.8 1.8 0 01-2.6-2.6l7.9-7.9"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Attachments({ items }: { items: TicketAttachment[] }) {
  if (!items.length) return null;
  return (
    <div className={styles.attachments}>
      {items.map((att) => {
        const url = supportUrl(att.url);
        if (att.kind === 'image') {
          return (
            <a key={att.id} href={url} target="_blank" rel="noreferrer" className={styles.imageLink}>
              <img src={url} alt={att.filename} className={styles.image} loading="lazy" />
            </a>
          );
        }
        if (att.kind === 'video') {
          return <video key={att.id} src={url} controls preload="metadata" className={styles.video} />;
        }
        return (
          <a key={att.id} href={url} target="_blank" rel="noreferrer" className={styles.docLink}>
            <span className={styles.docName}>📄 {att.filename}</span>
            <span className={styles.docSize}>{formatFileSize(att.size)}</span>
          </a>
        );
      })}
    </div>
  );
}

export function SupportChatPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { userId } = useAuth();
  const navOrderId = (location.state as SupportChatNavState | null)?.orderId ?? null;

  // `null` — chat hali yaratilmagan (foydalanuvchi birinchi marta yozadi).
  const [chat, setChat] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState<PendingMessage[]>([]);
  const [orderContext, setOrderContext] = useState<number | null>(navOrderId);

  const threadRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const stickToBottom = useRef(true);
  const readTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const pendingKey = useRef(0);

  const load = useCallback(async () => {
    try {
      const res = await getConversation();
      setChat(res.conversation);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Chat yuklanmadi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    stickToBottom.current = true;
    void load();
    return () => clearTimeout(readTimer.current);
  }, [load]);

  // Yangi xabar kelganda pastga surish — faqat foydalanuvchi pastda turgan bo'lsa
  // (eski xabarlarni o'qiyotganida sakrab ketmasin).
  const lastMessageId = chat?.messages[chat.messages.length - 1]?.id;
  useEffect(() => {
    if (stickToBottom.current) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lastMessageId, pending.length]);

  // Composer: matnga qarab o'sadi (COMPOSER_MAX_HEIGHT gacha), keyin ichida aylanadi.
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, COMPOSER_MAX_HEIGHT)}px`;
  }, [draft]);

  function onThreadScroll() {
    const el = threadRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function scheduleRead() {
    clearTimeout(readTimer.current);
    readTimer.current = setTimeout(() => {
      void markConversationRead().catch(() => undefined);
    }, 500);
  }

  /** Yuborilgan (yoki WS orqali kelgan) xabarni chatga qo'shadi. */
  function applyCreated(created: TicketMessageCreated) {
    const message = stripTicket(created);
    setChat((prev) =>
      prev
        ? { ...prev, ...created.ticket, messages: appendUnique(prev.messages, message) }
        : prev,
    );
  }

  useSupportEvents((event) => {
    if (event.type === 'resync') {
      void load();
      return;
    }
    if (event.type === 'message.created') {
      // Chat hali yo'q edi — boshqa qurilmadan birinchi xabar yozilgan: to'liq yuklaymiz.
      if (!chat) {
        if (event.ticket.user_id === userId) void load();
        return;
      }
      if (event.ticket_id !== chat.id) return;
      setChat((prev) =>
        prev
          ? { ...mergeTicket(prev, event.ticket), messages: appendUnique(prev.messages, event.message) }
          : prev,
      );
      // Chat ochiq — kelgan javob o'qilgan hisoblanadi (qo'ng'iroq badge'i uchun).
      if (!event.message.is_system && event.message.author_user_id !== userId) scheduleRead();
      return;
    }
    if (event.type === 'ticket.updated' && chat && event.ticket.id === chat.id) {
      setChat((prev) => (prev ? mergeTicket(prev, event.ticket) : prev));
    }
  });

  async function loadOlder() {
    if (!chat || loadingOlder || !chat.messages.length) return;
    setLoadingOlder(true);
    const el = threadRef.current;
    const prevHeight = el?.scrollHeight ?? 0;
    try {
      const page = await listConversationMessages(chat.messages[0].id);
      stickToBottom.current = false;
      setChat((prev) =>
        prev
          ? {
              ...prev,
              messages: [...page.items.filter((m) => !prev.messages.some((p) => p.id === m.id)), ...prev.messages],
              has_more_messages: page.has_more,
            }
          : prev,
      );
      // Ko'rinish joyida qolsin (tepaga qo'shilgan xabarlar uni pastga surmasin).
      requestAnimationFrame(() => {
        if (el) el.scrollTop += el.scrollHeight - prevHeight;
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Xabarlar yuklanmadi');
    } finally {
      setLoadingOlder(false);
    }
  }

  /** Matnli xabar: darhol "yuborilmoqda" bo'lib ko'rinadi, WS javobidan keyin haqiqiysiga almashadi. */
  async function deliver(item: PendingMessage) {
    const wasEmpty = chat === null;
    try {
      const created = await sendSupportMessage({ body: item.body, orderId: item.orderId });
      setPending((list) => list.filter((p) => p.key !== item.key));
      // Birinchi xabar chatni yaratdi — to'liq ma'lumot (id, xabarlar) serverdan.
      if (wasEmpty) await load();
      else applyCreated(created);
    } catch (err) {
      const text = err instanceof ApiError ? err.message : 'Xabar yuborilmadi';
      setPending((list) => list.map((p) => (p.key === item.key ? { ...p, failed: text } : p)));
    }
  }

  function sendText() {
    const body = draft.trim();
    if (!body) return;
    pendingKey.current += 1;
    const item: PendingMessage = { key: pendingKey.current, body, orderId: orderContext, failed: null };
    stickToBottom.current = true;
    setPending((list) => [...list, item]);
    setDraft('');
    setOrderContext(null); // buyurtma faqat birinchi xabarga bog'lanadi
    inputRef.current?.focus();
    void deliver(item);
  }

  function retry(item: PendingMessage) {
    const again = { ...item, failed: null };
    setPending((list) => list.map((p) => (p.key === item.key ? again : p)));
    void deliver(again);
  }

  async function sendFile() {
    if (!file || uploading) return;
    setUploading(true);
    setError(null);
    const wasEmpty = chat === null;
    try {
      const created = await uploadSupportAttachment({ file, body: draft.trim(), orderId: orderContext });
      stickToBottom.current = true;
      if (wasEmpty) await load();
      else applyCreated(created);
      setDraft('');
      setFile(null);
      setOrderContext(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Fayl yuborilmadi');
    } finally {
      setUploading(false);
    }
  }

  const canSend = file ? !uploading : draft.trim().length > 0;

  function send() {
    if (!canSend) return;
    if (file) void sendFile();
    else sendText();
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Mobil klaviaturada Enter — yangi qator; kompyuterda Ctrl/Cmd+Enter — yuborish.
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      send();
    }
  }

  function onPickFile(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    e.target.value = ''; // o'sha faylni qayta tanlash ham ishlasin
    setFile(picked);
    setError(null);
  }

  function goBack() {
    if (window.history.length > 1) navigate(-1);
    else navigate('/');
  }

  function authorLabel(message: TicketMessage): string {
    const role = message.author_role ? SUPPORT_ROLE_LABELS[message.author_role] ?? message.author_role : null;
    if (message.author_name) return `${message.author_name}${role ? ` · ${role}` : ''}`;
    return 'Yordam xizmati';
  }

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.centered} role="status" aria-label="Yuklanmoqda">
          <div className={styles.spinner} />
        </div>
      </div>
    );
  }

  const messages = chat?.messages ?? [];
  const resolved = chat != null && (chat.status === 'resolved' || chat.status === 'closed');

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={goBack} aria-label="Orqaga">
          ←
        </button>
        <div className={styles.headText}>
          <h1 className={styles.subject}>Yordam xizmati</h1>
          <div className={styles.meta}>
            {chat?.assigned_name ? `Operator: ${chat.assigned_name}` : 'Savolingizni yozing — shu yerda javob beramiz'}
          </div>
        </div>
      </div>

      <div
        className={styles.thread}
        ref={threadRef}
        onScroll={onThreadScroll}
        role="log"
        aria-live="polite"
        aria-label="Yozishma"
      >
        {chat?.has_more_messages && (
          <button className={styles.olderBtn} onClick={loadOlder} disabled={loadingOlder}>
            {loadingOlder ? 'Yuklanmoqda...' : 'Oldingi xabarlar'}
          </button>
        )}

        {messages.length === 0 && pending.length === 0 && (
          <div className={styles.intro}>
            <div className={styles.introTitle}>Assalomu alaykum!</div>
            Bu — yordam xizmati bilan chatingiz. Savol yoki muammoingizni yozing, rasm yoki hujjat ham
            yuborishingiz mumkin. Barcha savollaringiz shu bitta chatda saqlanadi.
          </div>
        )}

        {messages.map((message) => {
          if (message.is_system) {
            return (
              <div key={message.id} className={styles.system}>
                <span className={styles.systemBubble}>{message.body}</span>
              </div>
            );
          }
          const own =
            userId != null ? message.author_user_id === userId : message.author_user_id === chat?.user_id;
          return (
            <div key={message.id} className={own ? styles.mine : styles.theirs}>
              {!own && <div className={styles.author}>{authorLabel(message)}</div>}
              {message.order_id != null && <div className={styles.orderTag}>Buyurtma #{message.order_id}</div>}
              {message.body && <div className={styles.bubble}>{message.body}</div>}
              <Attachments items={message.attachments} />
              <div className={styles.time}>{formatShortDateTime(message.created_at)}</div>
            </div>
          );
        })}

        {pending.map((item) => (
          <div
            key={`pending-${item.key}`}
            className={`${styles.mine} ${item.failed ? styles.failed : styles.pending}`}
          >
            {item.orderId != null && <div className={styles.orderTag}>Buyurtma #{item.orderId}</div>}
            <div className={styles.bubble}>{item.body}</div>
            {item.failed ? (
              <div className={styles.failedRow}>
                <span>{item.failed}</span>
                <button className={styles.retryBtn} onClick={() => retry(item)}>
                  Qayta yuborish
                </button>
              </div>
            ) : (
              <div className={styles.time}>Yuborilmoqda...</div>
            )}
          </div>
        ))}

        {resolved && pending.length === 0 && (
          <div className={styles.statusNote}>
            Savolingiz hal qilindi deb belgilangan. Yana savol bo'lsa — shu yerga yozavering.
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      <div className={styles.composerWrap}>
        {orderContext != null && (
          <div className={styles.orderChip}>
            <span className={styles.orderChipText}>Buyurtma #{orderContext} bo'yicha</span>
            <button
              className={styles.fileChipRemove}
              onClick={() => setOrderContext(null)}
              aria-label="Buyurtmani olib tashlash"
            >
              ×
            </button>
          </div>
        )}
        {file && (
          <div className={styles.fileChip}>
            <span className={styles.fileChipName}>
              📎 {file.name} · {formatFileSize(file.size)}
            </span>
            <button
              className={styles.fileChipRemove}
              onClick={() => setFile(null)}
              aria-label="Biriktirmani olib tashlash"
            >
              ×
            </button>
          </div>
        )}
        <div className={styles.composer}>
          <input
            ref={fileInputRef}
            type="file"
            accept={ATTACHMENT_ACCEPT}
            className={styles.hiddenInput}
            onChange={onPickFile}
            tabIndex={-1}
            aria-hidden="true"
          />
          <button
            className={styles.attachBtn}
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            aria-label="Rasm, video yoki hujjat biriktirish"
          >
            <PaperclipIcon />
          </button>
          <textarea
            ref={inputRef}
            className={styles.input}
            value={draft}
            rows={1}
            maxLength={5000}
            placeholder={file ? 'Izoh (ixtiyoriy)...' : 'Xabar yozing...'}
            aria-label="Xabar matni"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <button className={styles.sendBtn} disabled={!canSend} onClick={send} aria-label="Yuborish">
            {uploading ? '...' : '↑'}
          </button>
        </div>
      </div>
    </div>
  );
}
