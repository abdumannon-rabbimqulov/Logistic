import { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import {
  TICKET_STATUS_LABELS,
  listTickets,
  mergeTicket,
  previewText,
  useSupportEvents,
} from '../api/support';
import type { TicketListItem } from '../types/api';
import { useAuth } from '../auth/AuthProvider';
import { BottomNav } from '../components/BottomNav';
import { DriverBottomNav } from '../components/DriverBottomNav';
import { MessagesNavIcon } from '../components/icons';
import { NewTicketSheet } from '../components/NewTicketSheet';
import styles from './MessagesPage.module.css';

// Murojaatlar (ticket) ro'yxati — support mikroservisidan olinadi (GET /support/tickets).
// Oddiy foydalanuvchi faqat o'zinikini ko'radi, filtr serverda majburlanadi.
// Ro'yxat sahifalab yuklanadi ("Yana ko'rsatish") va `/support/ws` orqali jonli
// yangilanadi: yangi javob kelgan murojaat tepaga chiqadi, o'qilmaganlar soni ortadi.

/** Buyurtma sahifasidan "Muammo bormi?" bilan kelinganda shu ekran darhol yangi
 *  murojaat formasini ochadi va buyurtma raqamini oldindan to'ldiradi. */
interface MessagesNavState {
  newTicketForOrderId?: number;
}

const PAGE_SIZE = 20;
const STAFF_ROLES = new Set(['admin', 'manager']);

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('uz-UZ');
}

function byActivity(a: TicketListItem, b: TicketListItem): number {
  return b.last_message_at.localeCompare(a.last_message_at) || b.id - a.id;
}

export function MessagesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { role, userId } = useAuth();
  const prefillOrderId = (location.state as MessagesNavState | null)?.newTicketForOrderId;

  // Bu ekran ikkala ilovada ham (sender va haydovchi) ishlatiladi, pastki menyu esa
  // ularda har xil — shuning uchun rolga qarab tanlanadi.
  const Nav = role === 'driver' ? DriverBottomNav : BottomNav;

  const [tickets, setTickets] = useState<TicketListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(prefillOrderId != null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const page = await listTickets({ limit: PAGE_SIZE });
      setTickets(page.items);
      setTotal(page.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Murojaatlar yuklanmadi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function loadMore() {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const page = await listTickets({ limit: PAGE_SIZE, offset: tickets.length });
      setTickets((prev) => {
        const seen = new Set(prev.map((t) => t.id));
        return [...prev, ...page.items.filter((t) => !seen.has(t.id))];
      });
      setTotal(page.total);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Murojaatlar yuklanmadi');
    } finally {
      setLoadingMore(false);
    }
  }

  useSupportEvents((event) => {
    if (event.type === 'resync' || event.type === 'ticket.created') {
      void load();
      return;
    }
    if (event.type !== 'message.created' && event.type !== 'ticket.updated') return;

    // Handler har renderda yangilanadi (useSupportEvents), shuning uchun `tickets` dolzarb.
    const update = event.ticket;
    const index = tickets.findIndex((t) => t.id === update.id);
    if (index === -1) {
      // Ro'yxatda yo'q (keyingi sahifada) — yangi faollik bo'lsa ro'yxatni yangilaymiz.
      if (event.type === 'message.created') void load();
      return;
    }
    const current = tickets[index];
    let next = mergeTicket(current, update);
    if (event.type === 'message.created') {
      const fromOtherSide =
        !event.message.is_system && event.message.author_user_id !== (userId ?? current.user_id);
      if (fromOtherSide) next = { ...next, unread_count: current.unread_count + 1 };
    } else {
      // Ruxsat etilgan holatlar ko'ruvchiga bog'liq; egasi uchun — faqat yopish.
      next = { ...next, allowed_statuses: next.status === 'closed' ? [] : ['closed'] };
    }
    const copy = [...tickets];
    copy[index] = next;
    setTickets(copy.sort(byActivity));
  });

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <h1 className={styles.title}>Murojaatlar</h1>
        <button className={styles.newBtn} onClick={() => setSheetOpen(true)}>
          Yangi murojaat
        </button>
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {loading ? (
        <div className={styles.list}>
          <div className={styles.skeleton} />
          <div className={styles.skeleton} />
          <div className={styles.skeleton} />
        </div>
      ) : tickets.length === 0 ? (
        <div className={styles.empty}>
          <MessagesNavIcon size={40} color="var(--color-gray-300)" strokeWidth={1.5} />
          <div className={styles.emptyTitle}>Murojaatlar yo'q</div>
          <div className={styles.emptyHint}>
            Savol yoki muammo bo'lsa, "Yangi murojaat" tugmasi orqali yozing — javobni shu
            yerda olasiz
          </div>
        </div>
      ) : (
        <div className={styles.list}>
          {tickets.map((ticket) => {
            const preview = previewText(ticket);
            const unread = ticket.unread_count > 0;
            return (
              <button
                key={ticket.id}
                className={unread ? `${styles.card} ${styles.cardUnread}` : styles.card}
                onClick={() => navigate(`/messages/${ticket.id}`)}
                aria-label={
                  unread
                    ? `${ticket.subject}, ${ticket.unread_count} ta o'qilmagan javob`
                    : ticket.subject
                }
              >
                <div className={styles.cardTop}>
                  <span className={styles.subject}>{ticket.subject}</span>
                  <span className={`${styles.badge} ${styles[`status_${ticket.status}`]}`}>
                    {TICKET_STATUS_LABELS[ticket.status]}
                  </span>
                </div>
                {preview && (
                  <div className={styles.preview}>
                    {ticket.last_message &&
                      !ticket.last_message.is_system &&
                      STAFF_ROLES.has(ticket.last_message.author_role ?? '') && (
                        <span className={styles.previewAuthor}>Yordam xizmati: </span>
                      )}
                    {preview}
                  </div>
                )}
                <div className={styles.cardMeta}>
                  <span>#{ticket.id}</span>
                  {ticket.order_id != null && <span>Buyurtma #{ticket.order_id}</span>}
                  <span>{formatDate(ticket.last_message_at)}</span>
                  {unread && (
                    <span className={styles.unreadDot} aria-hidden="true">
                      {ticket.unread_count}
                    </span>
                  )}
                </div>
              </button>
            );
          })}

          {tickets.length < total && (
            <button className={styles.moreBtn} onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? 'Yuklanmoqda...' : `Yana ko'rsatish (${total - tickets.length})`}
            </button>
          )}
        </div>
      )}

      {sheetOpen && (
        <NewTicketSheet
          orderId={prefillOrderId}
          onClose={() => setSheetOpen(false)}
          onCreated={(ticket) => {
            setSheetOpen(false);
            navigate(`/messages/${ticket.id}`);
          }}
        />
      )}

      <Nav />
    </div>
  );
}
