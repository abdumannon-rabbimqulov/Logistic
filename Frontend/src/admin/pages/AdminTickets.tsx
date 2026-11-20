import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ApiError } from '../../api/client';
import {
  ACTIVE_TICKET_STATUSES,
  SUPPORT_ROLE_LABELS,
  TICKET_STATUS_LABELS,
  assignTicketToMe,
  formatFileSize,
  getTicket,
  listTicketMessages,
  listTickets,
  markTicketRead,
  mergeTicket,
  previewText,
  sendSupportMessage,
  supportUrl,
  unassignTicket,
  updateTicketStatus,
  useSupportEvents,
} from '../../api/support';
import { useAuth } from '../../auth/AuthProvider';
import type { TicketDetail, TicketListItem, TicketMessage, TicketStatus } from '../../types/api';
import { DataTable } from '../components/DataTable';
import type { Column } from '../components/DataTable';
import { Modal } from '../components/Modal';
import { useToast } from '../components/Toast';
import shared from '../shared.module.css';
import styles from './AdminTickets.module.css';
import { formatDateTime } from '../../utils/format';

// Yordam chatlari — support MIKROSERVISIDAN (`/support/...`, `/api` ostida emas).
// Har foydalanuvchiga BITTA chat: uning barcha savollari shu yerda, tarix bilan.
// Xodim (admin/manager) hamma chatni ko'radi, o'ziga oladi va holatini (yangi /
// ko'rib chiqilmoqda / hal qilindi) o'zgartiradi — chat yopilmaydi; foydalanuvchi
// hal qilingan chatga yozsa u o'zi qayta ochiladi (support_service/rules.py).
// Ro'yxat va ochiq chat `/support/ws` orqali jonli; javob ham WS orqali yuboriladi.

const PAGE_SIZE = 50;
const REPLY_MAX_HEIGHT = 200;

type AssignedFilter = '' | 'me' | 'none';

function roleLabel(role: string | null): string {
  return role ? SUPPORT_ROLE_LABELS[role] ?? role : '-';
}

function appendUnique(list: TicketMessage[], message: TicketMessage): TicketMessage[] {
  return list.some((m) => m.id === message.id) ? list : [...list, message];
}

export function AdminTickets() {
  const toast = useToast();
  const { userId } = useAuth();

  const [rows, setRows] = useState<TicketListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<TicketStatus | ''>('');
  const [assignedFilter, setAssignedFilter] = useState<AssignedFilter>('');
  const [page, setPage] = useState(0);

  const [active, setActive] = useState<TicketDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState(false);
  const replyRef = useRef<HTMLTextAreaElement>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const readTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const load = useCallback(async () => {
    setError(null);
    try {
      const result = await listTickets({
        status: statusFilter || undefined,
        assigned: assignedFilter || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setRows(result.items);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Chatlar yuklanmadi');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, assignedFilter, page]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  useEffect(() => () => clearTimeout(readTimer.current), []);

  // Javob maydoni matnga qarab o'sadi.
  useLayoutEffect(() => {
    const el = replyRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, REPLY_MAX_HEIGHT)}px`;
  }, [reply, active?.id]);

  const lastMessageId = active?.messages[active.messages.length - 1]?.id;
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ block: 'end' });
  }, [lastMessageId]);

  /** Server qaytargan yangi ko'rinishni jadval qatoriga ham yozadi. */
  function patchRow(summary: TicketListItem) {
    setRows((prev) => prev.map((r) => (r.id === summary.id ? summary : r)));
  }

  async function openTicket(row: TicketListItem) {
    setDetailLoading(true);
    setReply('');
    try {
      const detail = await getTicket(row.id);
      setActive(detail);
      // Ochildi — o'qilgan (server `getTicket` da belgiladi).
      patchRow({ ...detail, unread_count: 0 });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Chat ochilmadi');
    } finally {
      setDetailLoading(false);
    }
  }

  async function refreshActive(ticketId: number) {
    try {
      const detail = await getTicket(ticketId);
      setActive((prev) => (prev && prev.id === ticketId ? detail : prev));
      patchRow({ ...detail, unread_count: 0 });
    } catch {
      // Ochiq oyna — keyingi hodisada qayta urinadi.
    }
  }

  useSupportEvents((event) => {
    if (event.type === 'resync' || event.type === 'ticket.created') {
      void load();
      if (event.type === 'resync' && active) void refreshActive(active.id);
      return;
    }
    if (event.type !== 'message.created' && event.type !== 'ticket.updated') return;

    const update = event.ticket;
    const isActive = active?.id === update.id;

    if (event.type === 'message.created') {
      const fromOwner = !event.message.is_system && event.message.author_user_id === update.user_id;
      setRows((prev) =>
        prev.map((r) =>
          r.id === update.id
            ? {
                ...mergeTicket(r, update),
                unread_count: fromOwner && !isActive ? r.unread_count + 1 : r.unread_count,
              }
            : r,
        ),
      );
      if (isActive) {
        setActive((prev) =>
          prev ? { ...mergeTicket(prev, update), messages: appendUnique(prev.messages, event.message) } : prev,
        );
        if (fromOwner) {
          clearTimeout(readTimer.current);
          readTimer.current = setTimeout(() => void markTicketRead(update.id).catch(() => undefined), 500);
        }
      }
      return;
    }

    // ticket.updated — holat yoki mas'ul o'zgardi; ruxsat etilgan holatlar ham o'zgaradi.
    setRows((prev) => prev.map((r) => (r.id === update.id ? mergeTicket(r, update) : r)));
    if (isActive) void refreshActive(update.id);
  });

  async function loadOlder() {
    if (!active || loadingOlder || !active.messages.length) return;
    setLoadingOlder(true);
    try {
      const older = await listTicketMessages(active.id, active.messages[0].id);
      setActive((prev) =>
        prev
          ? {
              ...prev,
              messages: [...older.items.filter((m) => !prev.messages.some((p) => p.id === m.id)), ...prev.messages],
              has_more_messages: older.has_more,
            }
          : prev,
      );
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Xabarlar yuklanmadi');
    } finally {
      setLoadingOlder(false);
    }
  }

  async function sendReply() {
    if (!active || !reply.trim() || busy) return;
    setBusy(true);
    try {
      const { ticket: summary, ...message } = await sendSupportMessage({ ticketId: active.id, body: reply.trim() });
      // Server javobdan keyin holatni o'zi o'zgartiradi (OPEN → IN_PROGRESS, mas'ul) —
      // javobdagi `ticket` bilan modal ham, jadval ham darhol yangilanadi.
      setActive((prev) => (prev ? { ...prev, ...summary, messages: appendUnique(prev.messages, message) } : prev));
      patchRow(summary);
      setReply('');
      toast.success('Javob yuborildi');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Javob yuborilmadi');
    } finally {
      setBusy(false);
    }
  }

  async function changeStatus(status: TicketStatus) {
    if (!active || busy || status === active.status) return;
    setBusy(true);
    try {
      const summary = await updateTicketStatus(active.id, status);
      setActive((prev) => (prev ? { ...prev, ...summary } : prev));
      patchRow(summary);
      toast.success('Holat yangilandi');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Holat o'zgartirilmadi");
    } finally {
      setBusy(false);
    }
  }

  async function toggleAssign() {
    if (!active || busy) return;
    setBusy(true);
    try {
      const summary =
        active.assigned_to === userId ? await unassignTicket(active.id) : await assignTicketToMe(active.id);
      setActive((prev) => (prev ? { ...prev, ...summary } : prev));
      patchRow(summary);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Biriktirib bo'lmadi");
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<TicketListItem>[] = [
    { key: 'id', header: 'ID', width: '70px', render: (r) => `#${r.id}` },
    {
      key: 'user',
      header: 'Foydalanuvchi',
      render: (r) => (
        <div className={styles.subjectCell}>
          <div className={styles.subjectLine}>
            <span className={r.unread_count > 0 ? styles.subjectUnread : undefined}>
              {r.user_name ?? `#${r.user_id}`} ({roleLabel(r.user_role)})
            </span>
            {r.unread_count > 0 && (
              <span className={styles.unreadBadge} title="O'qilmagan xabarlar">
                {r.unread_count}
              </span>
            )}
          </div>
          {r.last_message && <div className={styles.preview}>{previewText(r)}</div>}
        </div>
      ),
    },
    {
      key: 'order_id',
      header: 'Oxirgi buyurtma',
      render: (r) => (r.order_id != null ? `#${r.order_id}` : '—'),
    },
    {
      key: 'status',
      header: 'Holat',
      render: (r) => (
        <span className={`${styles.badge} ${styles[`status_${r.status}`]}`}>
          {TICKET_STATUS_LABELS[r.status]}
        </span>
      ),
    },
    {
      key: 'assigned',
      header: "Mas'ul",
      render: (r) => (r.assigned_to == null ? '—' : r.assigned_to === userId ? 'Men' : r.assigned_name ?? `#${r.assigned_to}`),
    },
    { key: 'last_message_at', header: 'Oxirgi faollik', render: (r) => formatDateTime(r.last_message_at) },
  ];

  const from = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const to = Math.min(total, (page + 1) * PAGE_SIZE);

  function authorLabel(m: TicketMessage, ticket: TicketDetail): string {
    if (m.author_user_id === ticket.user_id) return ticket.user_name ?? 'Foydalanuvchi';
    if (m.author_user_id === userId) return 'Siz';
    return m.author_name ? `${m.author_name} (${roleLabel(m.author_role)})` : 'Xodim';
  }

  return (
    <div className={shared.page}>
      <div className={shared.pageHead}>
        <div>
          <h1 className={shared.pageTitle}>Yordam chatlari</h1>
          <div className={shared.pageSub}>
            Har foydalanuvchiga bitta chat — uning barcha savol va shikoyatlari shu yerda
          </div>
        </div>
      </div>

      <div className={shared.toolbar}>
        <select
          className={shared.select}
          value={statusFilter}
          aria-label="Holat bo'yicha filtr"
          onChange={(e) => {
            setStatusFilter(e.target.value as TicketStatus | '');
            setPage(0);
          }}
        >
          <option value="">Barcha holatlar</option>
          {ACTIVE_TICKET_STATUSES.map((s) => (
            <option key={s} value={s}>
              {TICKET_STATUS_LABELS[s]}
            </option>
          ))}
        </select>

        <select
          className={shared.select}
          value={assignedFilter}
          aria-label="Mas'ul bo'yicha filtr"
          onChange={(e) => {
            setAssignedFilter(e.target.value as AssignedFilter);
            setPage(0);
          }}
        >
          <option value="">Hamma chatlar</option>
          <option value="me">Menga biriktirilgan</option>
          <option value="none">Hech kimga biriktirilmagan</option>
        </select>

        <span className={styles.pageInfo}>
          {from}–{to} / {total}
        </span>
        <button
          className={shared.ghostBtn}
          disabled={page === 0}
          onClick={() => setPage((p) => Math.max(0, p - 1))}
        >
          ← Oldingi
        </button>
        <button
          className={shared.ghostBtn}
          disabled={(page + 1) * PAGE_SIZE >= total}
          onClick={() => setPage((p) => p + 1)}
        >
          Keyingi →
        </button>
      </div>

      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={loading}
        error={error}
        emptyText="Chat yo'q"
        onRowClick={openTicket}
      />

      {(active || detailLoading) && (
        <Modal
          title={active ? `${active.user_name ?? `Foydalanuvchi #${active.user_id}`} — chat #${active.id}` : 'Yuklanmoqda...'}
          onClose={() => setActive(null)}
          footer={
            active && (
              <div className={styles.footer}>
                <div className={styles.footerLeft}>
                  <select
                    className={shared.select}
                    value={active.status}
                    disabled={busy || active.allowed_statuses.length === 0}
                    aria-label="Chat holati"
                    onChange={(e) => void changeStatus(e.target.value as TicketStatus)}
                  >
                    {[active.status, ...active.allowed_statuses].map((s) => (
                      <option key={s} value={s}>
                        {TICKET_STATUS_LABELS[s]}
                      </option>
                    ))}
                  </select>
                  <button className={shared.ghostBtn} disabled={busy} onClick={toggleAssign}>
                    {active.assigned_to === userId ? "Bo'shatish" : "O'zimga olish"}
                  </button>
                </div>
                <button className={shared.ghostBtn} onClick={() => setActive(null)}>
                  Yopish
                </button>
              </div>
            )
          }
        >
          {detailLoading || !active ? (
            <div className={styles.loadingBox}>Yuklanmoqda...</div>
          ) : (
            <div className={styles.detail}>
              <div className={styles.detailMeta}>
                {active.user_name ?? `Foydalanuvchi #${active.user_id}`} ({roleLabel(active.user_role)}, id{' '}
                {active.user_id})
                {active.order_id != null && ` · Oxirgi buyurtma #${active.order_id}`} · Chat ochilgan:{' '}
                {formatDateTime(active.created_at)}
                {' · '}Mas'ul: {active.assigned_name ?? (active.assigned_to != null ? `#${active.assigned_to}` : '—')}
              </div>

              <div className={styles.thread} role="log" aria-live="polite" aria-label="Yozishma">
                {active.has_more_messages && (
                  <button className={styles.olderBtn} onClick={loadOlder} disabled={loadingOlder}>
                    {loadingOlder ? 'Yuklanmoqda...' : 'Oldingi xabarlar'}
                  </button>
                )}

                {active.messages.map((m) =>
                  m.is_system ? (
                    <div key={m.id} className={styles.systemMsg}>
                      {m.body}
                    </div>
                  ) : (
                    <div
                      key={m.id}
                      className={m.author_user_id === active.user_id ? styles.userMsg : styles.staffMsg}
                    >
                      <div className={styles.msgAuthor}>
                        {authorLabel(m, active)}
                        {m.order_id != null && ` · Buyurtma #${m.order_id}`}
                      </div>
                      {m.body && <div className={styles.msgBody}>{m.body}</div>}
                      {m.attachments.map((att) => {
                        const url = supportUrl(att.url);
                        return att.kind === 'image' ? (
                          <a key={att.id} href={url} target="_blank" rel="noreferrer">
                            <img src={url} alt={att.filename} className={styles.attImage} loading="lazy" />
                          </a>
                        ) : att.kind === 'video' ? (
                          <video key={att.id} src={url} controls preload="metadata" className={styles.attImage} />
                        ) : (
                          <a key={att.id} href={url} target="_blank" rel="noreferrer" className={styles.attDoc}>
                            📄 {att.filename} · {formatFileSize(att.size)}
                          </a>
                        );
                      })}
                      <div className={styles.msgTime}>{formatDateTime(m.created_at)}</div>
                    </div>
                  ),
                )}
                <div ref={threadEndRef} />
              </div>

              {(active.status === 'resolved' || active.status === 'closed') && (
                <div className={styles.closedNote}>
                  Chat hal qilingan deb belgilangan. Foydalanuvchi yana yozsa — o'zi qayta ochiladi.
                </div>
              )}
              <div className={styles.replyBox}>
                <textarea
                  ref={replyRef}
                  className={`${styles.replyInput} resize-none`}
                  rows={2}
                  maxLength={5000}
                  value={reply}
                  placeholder="Javob yozing... (Ctrl+Enter — yuborish)"
                  aria-label="Javob matni"
                  onChange={(e) => setReply(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      void sendReply();
                    }
                  }}
                />
                <button
                  className={shared.primaryBtn}
                  disabled={!reply.trim() || busy}
                  onClick={sendReply}
                >
                  {busy ? 'Yuborilmoqda...' : 'Javob yuborish'}
                </button>
              </div>
            </div>
          )}
        </Modal>
      )}
    </div>
  );
}
