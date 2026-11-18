import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ChangeEvent, KeyboardEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import {
  ATTACHMENT_ACCEPT,
  SUPPORT_ROLE_LABELS,
  TICKET_PRIORITY_LABELS,
  TICKET_STATUS_LABELS,
  formatFileSize,
  getTicket,
  isTicketClosed,
  listTicketMessages,
  markTicketRead,
  mergeTicket,
  replyToTicket,
  supportUrl,
  updateTicketStatus,
  uploadTicketAttachment,
  useSupportEvents,
} from '../api/support';
import { useAuth } from '../auth/AuthProvider';
import type { TicketAttachment, TicketDetail, TicketMessage } from '../types/api';
import styles from './TicketPage.module.css';

// Bitta murojaat (ticket) va uning yozishmalari — support mikroservisidan.
// Yozishmada uch xil xabar bo'ladi:
//   1. murojaat egasiniki — egasi uchun o'ngda (yashil), xodim uchun chapda;
//   2. xodim javobi — muallif ismi bilan;
//   3. `is_system: true` — markazda, kulrang (buyurtma hodisalaridan avtomatik).
// "Kim yozgan" `author_user_id` ni murojaat EGASI (`ticket.user_id`) bilan solishtirib
// aniqlanadi — `userId` hali yuklanmagan bo'lsa ham yoki xodim ochganda ham to'g'ri.
// Yangi xabarlar `/support/ws` orqali o'zi keladi.

const COMPOSER_MAX_HEIGHT = 140;

function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleString('uz-UZ', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function appendUnique(list: TicketMessage[], message: TicketMessage): TicketMessage[] {
  return list.some((m) => m.id === message.id) ? list : [...list, message];
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

export function TicketPage() {
  const { ticketId } = useParams<{ ticketId: string }>();
  const navigate = useNavigate();
  const { userId } = useAuth();
  const id = Number(ticketId);

  const [ticket, setTicket] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [closing, setClosing] = useState(false);

  const threadRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const stickToBottom = useRef(true);
  const readTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const load = useCallback(async () => {
    if (!Number.isFinite(id)) return;
    try {
      setTicket(await getTicket(id));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Murojaat yuklanmadi');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    stickToBottom.current = true;
    void load();
    return () => clearTimeout(readTimer.current);
  }, [load]);

  // Yangi xabar kelganda pastga surish — faqat foydalanuvchi pastda turgan bo'lsa
  // (eski xabarlarni o'qiyotganida sakrab ketmasin).
  const lastMessageId = ticket?.messages[ticket.messages.length - 1]?.id;
  useEffect(() => {
    if (stickToBottom.current) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lastMessageId]);

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
      void markTicketRead(id).catch(() => undefined);
    }, 500);
  }

  useSupportEvents((event) => {
    if (event.type === 'resync') {
      void load();
      return;
    }
    if (event.type === 'message.created' && event.ticket_id === id) {
      setTicket((prev) =>
        prev
          ? { ...mergeTicket(prev, event.ticket), messages: appendUnique(prev.messages, event.message) }
          : prev,
      );
      // Chat ochiq — kelgan javob o'qilgan hisoblanadi (qo'ng'iroq badge'i uchun).
      if (!event.message.is_system && event.message.author_user_id !== userId) scheduleRead();
      return;
    }
    if (event.type === 'ticket.updated' && event.ticket.id === id) {
      // Ruxsat etilgan holatlar ko'ruvchiga bog'liq — serverdan qayta olamiz.
      void load();
    }
  });

  async function loadOlder() {
    if (!ticket || loadingOlder || !ticket.messages.length) return;
    setLoadingOlder(true);
    const el = threadRef.current;
    const prevHeight = el?.scrollHeight ?? 0;
    try {
      const page = await listTicketMessages(ticket.id, ticket.messages[0].id);
      stickToBottom.current = false;
      setTicket((prev) =>
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

  const closed = ticket != null && isTicketClosed(ticket.status);
  const canClose = ticket?.allowed_statuses.includes('closed') ?? false;
  const canSend = (draft.trim().length > 0 || file != null) && !sending;

  async function send() {
    if (!ticket || !canSend) return;
    setSending(true);
    setError(null);
    try {
      const created = file
        ? await uploadTicketAttachment(ticket.id, file, draft.trim())
        : await replyToTicket(ticket.id, draft.trim());
      const { ticket: summary, ...message } = created;
      stickToBottom.current = true;
      setTicket((prev) =>
        prev ? { ...prev, ...summary, messages: appendUnique(prev.messages, message) } : prev,
      );
      setDraft('');
      setFile(null);
      inputRef.current?.focus();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Xabar yuborilmadi');
      // 409 — ticket shu orada yopilgan bo'lishi mumkin; holatni yangilab olamiz.
      if (err instanceof ApiError && err.status === 409) void load();
    } finally {
      setSending(false);
    }
  }

  async function closeTicket() {
    if (!ticket || closing) return;
    if (!window.confirm("Murojaatni yopasizmi? Yopilgan murojaatga qayta yozib bo'lmaydi.")) return;
    setClosing(true);
    try {
      const summary = await updateTicketStatus(ticket.id, 'closed');
      setTicket((prev) => (prev ? { ...prev, ...summary } : prev));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Murojaat yopilmadi');
    } finally {
      setClosing(false);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    // Mobil klaviaturada Enter — yangi qator; kompyuterda Ctrl/Cmd+Enter — yuborish.
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void send();
    }
  }

  function onPickFile(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0] ?? null;
    e.target.value = ''; // o'sha faylni qayta tanlash ham ishlasin
    setFile(picked);
    setError(null);
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

  if (!ticket) {
    return (
      <div className={styles.page}>
        <div className={styles.centered}>
          <div className={styles.errorText}>{error ?? 'Murojaat topilmadi'}</div>
          <button className={styles.backLink} onClick={() => navigate('/messages')}>
            Murojaatlarga qaytish
          </button>
        </div>
      </div>
    );
  }

  const isOwnerView = userId == null || userId === ticket.user_id;
  const ownerLabel = ticket.user_name ?? 'Foydalanuvchi';

  function authorLabel(message: TicketMessage): string {
    if (message.author_user_id === ticket!.user_id) return ownerLabel;
    const role = message.author_role ? SUPPORT_ROLE_LABELS[message.author_role] ?? message.author_role : null;
    if (message.author_name) return `${message.author_name}${role ? ` · ${role}` : ''}`;
    return 'Yordam xizmati';
  }

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate('/messages')} aria-label="Orqaga">
          ←
        </button>
        <div className={styles.headText}>
          <h1 className={styles.subject}>{ticket.subject}</h1>
          <div className={styles.meta}>
            #{ticket.id} · {TICKET_STATUS_LABELS[ticket.status]} ·{' '}
            {TICKET_PRIORITY_LABELS[ticket.priority]}
            {ticket.order_id != null && ` · Buyurtma #${ticket.order_id}`}
            {ticket.assigned_name && ` · Mas'ul: ${ticket.assigned_name}`}
          </div>
        </div>
        {canClose && (
          <button className={styles.closeTicketBtn} onClick={closeTicket} disabled={closing}>
            {closing ? '...' : 'Yopish'}
          </button>
        )}
      </div>

      <div
        className={styles.thread}
        ref={threadRef}
        onScroll={onThreadScroll}
        role="log"
        aria-live="polite"
        aria-label="Yozishma"
      >
        {ticket.has_more_messages ? (
          <button className={styles.olderBtn} onClick={loadOlder} disabled={loadingOlder}>
            {loadingOlder ? 'Yuklanmoqda...' : 'Oldingi xabarlar'}
          </button>
        ) : (
          // Murojaatning asosiy matni — birinchi xabar sifatida (eng boshiga yetganda).
          <div className={isOwnerView ? styles.mine : styles.theirs}>
            {!isOwnerView && <div className={styles.author}>{ownerLabel}</div>}
            <div className={styles.bubble}>{ticket.body}</div>
            <div className={styles.time}>{formatTime(ticket.created_at)}</div>
          </div>
        )}

        {ticket.messages.map((message) => {
          if (message.is_system) {
            return (
              <div key={message.id} className={styles.system}>
                <span className={styles.systemBubble}>{message.body}</span>
              </div>
            );
          }
          const own =
            userId != null ? message.author_user_id === userId : message.author_user_id === ticket.user_id;
          return (
            <div key={message.id} className={own ? styles.mine : styles.theirs}>
              {!own && <div className={styles.author}>{authorLabel(message)}</div>}
              {message.body && <div className={styles.bubble}>{message.body}</div>}
              <Attachments items={message.attachments} />
              <div className={styles.time}>{formatTime(message.created_at)}</div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {closed ? (
        <div className={styles.closedBar}>
          {ticket.status === 'closed'
            ? "Murojaat yopilgan — yangi xabar yozib bo'lmaydi. Savol qolgan bo'lsa yangi murojaat oching."
            : "Murojaat hal qilingan deb belgilandi. Muammo qolgan bo'lsa, yangi murojaat oching."}
        </div>
      ) : (
        <div className={styles.composerWrap}>
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
              disabled={sending}
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
              {sending ? '...' : '↑'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
