import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  deleteChatMessage,
  editChatMessage,
  getChatConversation,
  getChatMessages,
  markChatRead,
  sendChatMessage,
  syncChat,
  uploadChatMedia,
  type ChatConversation,
  type ChatMessage,
  type ChatReplyRef,
  type SendMessageInput,
} from '../api/chat';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthProvider';
import chatStyles from '../components/chat/Chat.module.css';
import { Composer, SheetItem, type MediaDraft } from '../components/chat/Composer';
import { MediaViewer } from '../components/chat/MediaViewer';
import { MessageBubble } from '../components/chat/MessageBubble';
import { dayKey, dayLabel } from '../components/chat/mediaUtils';
import type { UiMessage } from '../components/chat/types';
import { useChatSocket, type ChatSocketEvent } from '../hooks/useChatSocket';
import { getCurrentPositionOnce, PositionError } from '../utils/currentPosition';
import styles from './OrderChatPage.module.css';

// Buyurtma chati: yuk egasi ↔ haydovchi (chat_service). Sender va haydovchi
// router'larida bir xil yo'l — `/orders/:orderId/chat`.
//
// Ma'lumot oqimi:
//   * ochilganda — oxirgi 50 xabar + `sync` (suhbat holati va server vaqti);
//   * WebSocket — yangi/tahrirlangan xabar, ✓✓, "yozmoqda…";
//   * WS (qayta) ulanganda — `sync?after_id=<oxirgi>&since=<server_time>`;
//   * yuqoriga aylantirilganda — `before_id` bilan eski sahifa.
// Yuborish optimistik: xabar darhol lentada (🕓), server javobi `client_id` orqali
// almashtiradi; xato bo'lsa "!" — bosib qayta yuborish mumkin.

const PAGE = 50;
const NEAR_BOTTOM_PX = 120;
const NEAR_TOP_PX = 160;
const TYPING_SHOW_MS = 4500;
const EDIT_WINDOW_MS = 48 * 3600 * 1000;

function newClientId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

let tempSeq = 0;
const nextTempId = () => -(Date.now() * 10 + (tempSeq++ % 10));

/** Server xabarlarini lentaga qo'shadi/yangilaydi; shu `client_id` li optimistik
 *  nusxani olib tashlaydi. Tartib: server xabarlari id bo'yicha, keyin yuborilayotganlar. */
function mergeMessages(current: UiMessage[], incoming: ChatMessage[]): UiMessage[] {
  if (incoming.length === 0) return current;
  const byId = new Map<number, UiMessage>();
  const locals: UiMessage[] = [];
  const incomingClientIds = new Set(incoming.map((m) => m.client_id).filter(Boolean));
  for (const m of current) {
    if (m.id < 0) {
      if (m.client_id && incomingClientIds.has(m.client_id)) {
        if (m.local?.previewUrl) URL.revokeObjectURL(m.local.previewUrl);
        continue;
      }
      locals.push(m);
    } else {
      byId.set(m.id, m);
    }
  }
  for (const m of incoming) byId.set(m.id, m);
  const server = [...byId.values()].sort((a, b) => a.id - b.id);
  return [...server, ...locals];
}

export function OrderChatPage() {
  const { orderId: rawId } = useParams<{ orderId: string }>();
  const orderId = Number(rawId);
  const navigate = useNavigate();
  const { userId, role } = useAuth();

  const [conv, setConv] = useState<ChatConversation | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [fatal, setFatal] = useState<string | null>(null);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [peerTyping, setPeerTyping] = useState(false);
  const [reply, setReply] = useState<UiMessage | null>(null);
  const [editing, setEditing] = useState<UiMessage | null>(null);
  const [menuFor, setMenuFor] = useState<UiMessage | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [viewer, setViewer] = useState<UiMessage | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [highlightId, setHighlightId] = useState<number | null>(null);
  const [newBelow, setNewBelow] = useState(0);
  const [atBottom, setAtBottom] = useState(true);
  /** Ochilgan paytdagi o'qilgan belgisi — "O'qilmagan xabarlar" ajratgichi uchun. */
  const [unreadSince, setUnreadSince] = useState<number | null>(null);

  const listRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<UiMessage[]>([]);
  const convRef = useRef<ChatConversation | null>(null);
  const lastSyncRef = useRef<string | null>(null);
  const syncingRef = useRef(false);
  const stickToBottomRef = useRef(true);
  const prependHeightRef = useRef<number | null>(null);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const readInFlightRef = useRef(0);
  const retryRef = useRef(new Map<string, () => void>());

  messagesRef.current = messages;
  convRef.current = conv;

  const isDriver = role === 'driver' || conv?.my_role === 'driver';
  const peerLabel = conv?.my_role === 'driver' ? 'Yuk egasi' : 'Haydovchi';
  const backPath = isDriver ? `/active/${orderId}` : `/orders/${orderId}`;
  const blockedReason = conv?.write_blocked_reason ?? null;

  const showToast = useCallback((text: string) => {
    setToast(text);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(null), 3500);
  }, []);

  const nameOf = useCallback(
    (uid: number) => (uid === userId ? 'Siz' : peerLabel),
    [userId, peerLabel],
  );

  const maxServerId = () => {
    const list = messagesRef.current;
    for (let i = list.length - 1; i >= 0; i -= 1) if (list[i].id > 0) return list[i].id;
    return 0;
  };

  const applyIncoming = useCallback((incoming: ChatMessage[]) => {
    setMessages((cur) => mergeMessages(cur, incoming));
  }, []);

  // --- Yuklash va sinxronlash ---------------------------------------------------

  const doSync = useCallback(async () => {
    if (syncingRef.current || !Number.isFinite(orderId)) return;
    syncingRef.current = true;
    try {
      for (let i = 0; i < 5; i += 1) {
        const res = await syncChat(orderId, maxServerId(), lastSyncRef.current);
        lastSyncRef.current = res.server_time;
        setConv(res.conversation);
        const all = [...res.messages, ...res.changed];
        if (all.length) {
          const fresh = res.messages.filter((m) => m.sender_user_id !== userId).length;
          if (fresh && !stickToBottomRef.current) setNewBelow((n) => n + fresh);
          applyIncoming(all);
        }
        if (!res.has_more) break;
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setFatal('Chat topilmadi yoki sizga ochiq emas');
    } finally {
      syncingRef.current = false;
    }
  }, [orderId, userId, applyIncoming]);

  useEffect(() => {
    if (!Number.isFinite(orderId)) {
      setFatal('Buyurtma raqami noto‘g‘ri');
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const page = await getChatMessages(orderId, { limit: PAGE });
        if (cancelled) return;
        setMessages(page.messages);
        messagesRef.current = page.messages;
        setHasMore(page.has_more);
        stickToBottomRef.current = true;
        const res = await syncChat(orderId, maxServerId());
        if (cancelled) return;
        lastSyncRef.current = res.server_time;
        setUnreadSince(res.conversation.my_last_read_id);
        setConv(res.conversation);
        applyIncoming(res.messages);
      } catch (err) {
        if (cancelled) return;
        setFatal(
          err instanceof ApiError && err.status === 404
            ? "Chat hali ochilmagan. U haydovchi buyurtmani qabul qilgach paydo bo'ladi."
            : err instanceof ApiError
              ? err.message
              : 'Chat yuklanmadi. Internetni tekshiring.',
        );
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [orderId, applyIncoming]);

  // --- Real vaqt ---------------------------------------------------------------

  const onSocketEvent = useCallback(
    (event: ChatSocketEvent) => {
      if (event.order_id !== orderId) return;
      switch (event.type) {
        case 'message.new': {
          const mine = event.message.sender_user_id === userId;
          if (!mine) {
            setPeerTyping(false);
            if (!stickToBottomRef.current) setNewBelow((n) => n + 1);
          }
          applyIncoming([event.message]);
          break;
        }
        case 'message.edited':
          applyIncoming([event.message]);
          break;
        case 'message.read':
          setConv((c) => {
            if (!c) return c;
            if (event.user_id === userId) {
              return { ...c, my_last_read_id: Math.max(c.my_last_read_id, event.last_read_message_id) };
            }
            return { ...c, peer_last_read_id: Math.max(c.peer_last_read_id, event.last_read_message_id) };
          });
          break;
        case 'typing':
          if (event.user_id === userId) break;
          setPeerTyping(true);
          if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
          typingTimerRef.current = setTimeout(() => setPeerTyping(false), TYPING_SHOW_MS);
          break;
        case 'conversation.updated':
          void getChatConversation(orderId)
            .then(setConv)
            .catch((err) => {
              if (err instanceof ApiError && err.status === 404) setFatal('Chat sizga endi ochiq emas');
            });
          break;
      }
    },
    [orderId, userId, applyIncoming],
  );

  const { connected, sendTyping } = useChatSocket({
    onEvent: onSocketEvent,
    // Birinchi ulanishda ham: yuklash va obuna orasidagi oraliqda kelgan xabarlar.
    onOpen: () => void doSync(),
    enabled: !loading && !fatal,
  });

  useEffect(
    () => () => {
      if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      for (const m of messagesRef.current) if (m.local?.previewUrl) URL.revokeObjectURL(m.local.previewUrl);
    },
    [],
  );

  // --- Aylantirish ---------------------------------------------------------------

  const scrollToBottom = (smooth = false) => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
  };

  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    if (prependHeightRef.current != null) {
      // Eski xabarlar tepaga qo'shildi — ko'rinib turgan joy siljimasin.
      el.scrollTop += el.scrollHeight - prependHeightRef.current;
      prependHeightRef.current = null;
      return;
    }
    if (stickToBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [messages, peerTyping]);

  const loadOlder = useCallback(async () => {
    const first = messagesRef.current.find((m) => m.id > 0);
    if (!first || loadingOlder || !hasMore) return;
    setLoadingOlder(true);
    try {
      const page = await getChatMessages(orderId, { before_id: first.id, limit: PAGE });
      prependHeightRef.current = listRef.current?.scrollHeight ?? null;
      setHasMore(page.has_more);
      applyIncoming(page.messages);
    } catch {
      showToast('Eski xabarlar yuklanmadi');
    } finally {
      setLoadingOlder(false);
    }
  }, [orderId, loadingOlder, hasMore, applyIncoming, showToast]);

  const onScroll = () => {
    const el = listRef.current;
    if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    stickToBottomRef.current = bottom;
    if (bottom !== atBottom) setAtBottom(bottom);
    if (bottom && newBelow) setNewBelow(0);
    if (el.scrollTop < NEAR_TOP_PX) void loadOlder();
  };

  // --- O'qilgan belgisi -----------------------------------------------------------

  useEffect(() => {
    if (!conv || !atBottom || document.visibilityState !== 'visible') return;
    let lastPeer = 0;
    for (const m of messages) if (m.id > lastPeer && m.sender_user_id !== userId) lastPeer = m.id;
    if (lastPeer <= conv.my_last_read_id || lastPeer <= readInFlightRef.current) return;
    readInFlightRef.current = lastPeer;
    markChatRead(orderId, lastPeer)
      .then((res) =>
        setConv((c) =>
          c ? { ...c, my_last_read_id: Math.max(c.my_last_read_id, res.last_read_message_id), unread_count: res.unread_count } : c,
        ),
      )
      .catch(() => {
        readInFlightRef.current = 0;
      });
  }, [messages, atBottom, conv, orderId, userId]);

  useEffect(() => {
    // Ilova fondan qaytganda ham "o'qildi" qo'yilsin (yuqoridagi effekt qayta ishlasin).
    const onVisible = () => {
      if (document.visibilityState === 'visible') setConv((c) => (c ? { ...c } : c));
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  // --- Yuborish ------------------------------------------------------------------

  const replyRef = (m: UiMessage | null): ChatReplyRef | null =>
    m
      ? {
          id: m.id,
          sender_user_id: m.sender_user_id,
          kind: m.kind,
          preview: m.text ?? kindLabel(m.kind),
          deleted: false,
        }
      : null;

  const patchLocal = (clientId: string, patch: Partial<NonNullable<UiMessage['local']>>) =>
    setMessages((cur) =>
      cur.map((m) => (m.client_id === clientId && m.local ? { ...m, local: { ...m.local, ...patch } } : m)),
    );

  const enqueue = (local: UiMessage, run: () => Promise<ChatMessage>) => {
    const clientId = local.client_id!;
    stickToBottomRef.current = true;
    setMessages((cur) => [...cur, local]);
    const attempt = () => {
      patchLocal(clientId, { status: 'sending', error: undefined });
      run()
        .then((saved) => {
          retryRef.current.delete(clientId);
          applyIncoming([saved]);
        })
        .catch((err) => {
          const msg = err instanceof ApiError ? err.message : 'Xabar yuborilmadi';
          patchLocal(clientId, { status: 'failed', error: msg });
          showToast(msg);
          if (err instanceof ApiError && err.status === 409) void doSync();
        });
    };
    retryRef.current.set(clientId, attempt);
    attempt();
  };

  const baseLocal = (kind: UiMessage['kind'], extra: Partial<UiMessage> = {}): UiMessage => ({
    id: nextTempId(),
    order_id: orderId,
    sender_user_id: userId ?? 0,
    kind,
    text: null,
    media: null,
    duration_s: null,
    lat: null,
    lon: null,
    reply_to: replyRef(reply),
    client_id: newClientId(),
    created_at: new Date().toISOString(),
    edited_at: null,
    deleted_at: null,
    local: { status: 'sending' },
    ...extra,
  });

  const sendText = (text: string) => {
    const local = baseLocal('text', { text });
    const input: SendMessageInput = { kind: 'text', text, reply_to_id: reply?.id ?? null, client_id: local.client_id! };
    setReply(null);
    enqueue(local, () => sendChatMessage(orderId, input));
  };

  const sendMedia = (draft: MediaDraft) => {
    const local = baseLocal(draft.kind, {
      text: draft.caption ?? null,
      duration_s: draft.durationS ?? null,
      local: { status: 'sending', progress: 0, previewUrl: draft.previewUrl ?? undefined },
    });
    const clientId = local.client_id!;
    const replyToId = reply?.id ?? null;
    setReply(null);
    let mediaId: string | null = null; // qayta urinishda fayl qayta yuklanmasin
    enqueue(local, async () => {
      if (!mediaId) {
        const upload = uploadChatMedia(
          orderId,
          { kind: draft.kind, file: draft.file, fileName: draft.fileName, durationS: draft.durationS, thumb: draft.thumb },
          (p) => patchLocal(clientId, { progress: p }),
        );
        mediaId = (await upload.promise).id;
      }
      return sendChatMessage(orderId, {
        kind: draft.kind,
        media_id: mediaId,
        text: draft.caption ?? null,
        reply_to_id: replyToId,
        client_id: clientId,
      });
    });
  };

  const sendLocation = async () => {
    try {
      const pos = await getCurrentPositionOnce();
      const local = baseLocal('location', { lat: pos.latitude, lon: pos.longitude });
      const input: SendMessageInput = {
        kind: 'location',
        lat: pos.latitude,
        lon: pos.longitude,
        reply_to_id: reply?.id ?? null,
        client_id: local.client_id!,
      };
      setReply(null);
      enqueue(local, () => sendChatMessage(orderId, input));
    } catch (err) {
      showToast(err instanceof PositionError ? err.message : 'Joylashuv aniqlanmadi');
    }
  };

  const submitEdit = async (id: number, text: string) => {
    setEditing(null);
    try {
      applyIncoming([await editChatMessage(orderId, id, text)]);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Tahrirlanmadi');
    }
  };

  const doDelete = async (m: UiMessage) => {
    setMenuFor(null);
    setConfirmDelete(false);
    try {
      applyIncoming([await deleteChatMessage(orderId, m.id)]);
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : "O'chirilmadi");
    }
  };

  const discardLocal = (m: UiMessage) => {
    setMenuFor(null);
    if (m.client_id) retryRef.current.delete(m.client_id);
    if (m.local?.previewUrl) URL.revokeObjectURL(m.local.previewUrl);
    setMessages((cur) => cur.filter((x) => x !== m && x.client_id !== m.client_id));
  };

  const jumpTo = (id: number) => {
    const el = listRef.current?.querySelector(`[data-mid="${id}"]`);
    if (!el) {
      showToast('Xabar yuqoriroqda — eski xabarlarni yuklang');
      return;
    }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setHighlightId(id);
    setTimeout(() => setHighlightId((h) => (h === id ? null : h)), 1300);
  };

  const onOpenMenu = useCallback((m: UiMessage) => {
    setConfirmDelete(false);
    setMenuFor(m);
  }, []);
  const onOpenMedia = useCallback((m: UiMessage) => setViewer(m), []);
  const closeViewer = useCallback(() => setViewer(null), []);

  // --- Lenta (sana ajratgichlari bilan) ----------------------------------------------

  const feed = useMemo(() => {
    const out: { key: string; node: 'day' | 'unread' | 'msg'; label?: string; msg?: UiMessage }[] = [];
    let lastDay = '';
    let unreadPlaced = false;
    const since = unreadSince;
    for (const m of messages) {
      const dk = dayKey(m.created_at);
      if (dk !== lastDay) {
        out.push({ key: `d-${dk}`, node: 'day', label: dayLabel(m.created_at) });
        lastDay = dk;
      }
      if (!unreadPlaced && since != null && m.id > since && m.sender_user_id !== userId) {
        out.push({ key: 'unread', node: 'unread' });
        unreadPlaced = true;
      }
      out.push({ key: m.client_id && m.id < 0 ? `l-${m.client_id}` : `m-${m.id}`, node: 'msg', msg: m });
    }
    return out;
  }, [messages, userId, unreadSince]);

  // --- Render ------------------------------------------------------------------

  if (loading) {
    return (
      <div className={styles.page}>
        <div className={styles.centered}>
          <div className={styles.spinner} />
        </div>
      </div>
    );
  }

  if (fatal || !conv) {
    return (
      <div className={styles.page}>
        <div className={styles.centered}>
          <div className={styles.errorText}>{fatal ?? 'Chat topilmadi'}</div>
          <button className={styles.linkBtn} onClick={() => navigate(backPath)}>
            Buyurtmaga qaytish
          </button>
        </div>
      </div>
    );
  }

  const subtitle = peerTyping
    ? 'yozmoqda…'
    : !connected
      ? 'ulanmoqda…'
      : conv.status === 'readonly'
        ? 'chat yopilgan'
        : peerLabel;

  const menuMsg = menuFor;
  const menuMine = menuMsg != null && menuMsg.sender_user_id === userId;
  const canEditMenu =
    menuMsg != null &&
    menuMine &&
    !menuMsg.local &&
    !menuMsg.deleted_at &&
    !blockedReason &&
    (menuMsg.kind === 'text' || menuMsg.kind === 'photo' || menuMsg.kind === 'video' || menuMsg.kind === 'document') &&
    Date.now() - new Date(menuMsg.created_at).getTime() < EDIT_WINDOW_MS;

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <button className={styles.backBtn} onClick={() => navigate(backPath)} aria-label="Orqaga">
          ←
        </button>
        <div className={styles.avatar}>{conv.my_role === 'driver' ? '📦' : '🚚'}</div>
        <div className={styles.headText}>
          <div className={styles.title}>Buyurtma #{orderId}</div>
          <div className={`${styles.subtitle} ${peerTyping ? styles.subtitleTyping : ''}`}>{subtitle}</div>
        </div>
      </div>

      <div className={styles.listWrap}>
        {toast && <div className={styles.toast}>{toast}</div>}
        <div className={styles.list} ref={listRef} onScroll={onScroll}>
          <div className={styles.spacer} />
          {hasMore && <div className={styles.olderLoader}>{loadingOlder ? 'Yuklanmoqda…' : ' '}</div>}
          {messages.length === 0 && (
            <div className={styles.emptyHint}>
              Hali xabar yo'q. {peerLabel}ga birinchi bo'lib yozing — manzil, vaqt yoki yuk haqida
              aniqlashtiring.
            </div>
          )}
          {feed.map((item) =>
            item.node === 'day' ? (
              <div key={item.key} className={styles.day}>
                {item.label}
              </div>
            ) : item.node === 'unread' ? (
              <div key={item.key} className={styles.unreadDivider}>
                O'qilmagan xabarlar
              </div>
            ) : (
              <Fragment key={item.key}>
                <MessageBubble
                  message={item.msg!}
                  mine={item.msg!.sender_user_id === userId}
                  peerLastReadId={conv.peer_last_read_id}
                  nameOf={nameOf}
                  highlighted={highlightId === item.msg!.id}
                  onOpenMedia={onOpenMedia}
                  onQuoteClick={jumpTo}
                  onMenu={onOpenMenu}
                />
              </Fragment>
            ),
          )}
        </div>
        {!atBottom && (
          <button
            className={styles.toBottom}
            onClick={() => {
              stickToBottomRef.current = true;
              setNewBelow(0);
              scrollToBottom(true);
            }}
            aria-label="Pastga"
          >
            ↓{newBelow > 0 && <span className={styles.toBottomBadge}>{newBelow}</span>}
          </button>
        )}
      </div>

      <Composer
        blockedReason={blockedReason}
        reply={reply ? { title: `Javob: ${nameOf(reply.sender_user_id)}`, text: reply.text ?? kindLabel(reply.kind) } : null}
        onCancelReply={() => setReply(null)}
        editing={editing ? { id: editing.id, text: editing.text ?? '' } : null}
        onCancelEdit={() => setEditing(null)}
        onSendText={sendText}
        onSubmitEdit={(id, text) => void submitEdit(id, text)}
        onSendMedia={sendMedia}
        onSendLocation={() => void sendLocation()}
        onTyping={() => sendTyping(orderId)}
        onError={showToast}
      />

      {menuMsg && (
        <div className={chatStyles.backdrop} onClick={() => setMenuFor(null)}>
          <div className={chatStyles.sheet} onClick={(e) => e.stopPropagation()}>
            {menuMsg.local ? (
              <>
                {menuMsg.local.error && <div className={chatStyles.sheetTitle}>{menuMsg.local.error}</div>}
                {menuMsg.local.status === 'failed' && (
                  <SheetItem
                    icon="↻"
                    label="Qayta yuborish"
                    onClick={() => {
                      setMenuFor(null);
                      if (menuMsg.client_id) retryRef.current.get(menuMsg.client_id)?.();
                    }}
                  />
                )}
                <SheetItem icon="🗑" label="Bekor qilish" danger onClick={() => discardLocal(menuMsg)} />
              </>
            ) : confirmDelete ? (
              <>
                <div className={chatStyles.sheetTitle}>Xabar ikkala tomondan ham o'chiriladi.</div>
                <SheetItem icon="🗑" label="Ha, o'chirish" danger onClick={() => void doDelete(menuMsg)} />
                <SheetItem icon="✕" label="Bekor qilish" onClick={() => setMenuFor(null)} />
              </>
            ) : (
              <>
                {!menuMsg.deleted_at && !blockedReason && (
                  <SheetItem
                    icon="↩"
                    label="Javob berish"
                    onClick={() => {
                      setEditing(null);
                      setReply(menuMsg);
                      setMenuFor(null);
                    }}
                  />
                )}
                {menuMsg.text && !menuMsg.deleted_at && (
                  <SheetItem
                    icon="⧉"
                    label="Nusxa olish"
                    onClick={() => {
                      void navigator.clipboard?.writeText(menuMsg.text ?? '').then(
                        () => showToast('Nusxa olindi'),
                        () => showToast("Nusxa olib bo'lmadi"),
                      );
                      setMenuFor(null);
                    }}
                  />
                )}
                {canEditMenu && (
                  <SheetItem
                    icon="✎"
                    label={menuMsg.kind === 'text' ? 'Tahrirlash' : 'Izohni tahrirlash'}
                    onClick={() => {
                      setReply(null);
                      setEditing(menuMsg);
                      setMenuFor(null);
                    }}
                  />
                )}
                {menuMine && !menuMsg.deleted_at && !blockedReason && (
                  <SheetItem icon="🗑" label="O'chirish" danger onClick={() => setConfirmDelete(true)} />
                )}
                {menuMsg.deleted_at && <div className={chatStyles.sheetTitle}>Bu xabar o'chirilgan</div>}
              </>
            )}
          </div>
        </div>
      )}

      {viewer && <MediaViewer message={viewer} onClose={closeViewer} />}
    </div>
  );
}

function kindLabel(kind: UiMessage['kind']): string {
  switch (kind) {
    case 'photo':
      return '📷 Rasm';
    case 'video':
      return '🎬 Video';
    case 'voice':
      return '🎤 Ovozli xabar';
    case 'document':
      return '📄 Hujjat';
    case 'location':
      return '📍 Joylashuv';
    default:
      return '';
  }
}
