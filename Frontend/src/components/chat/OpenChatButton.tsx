import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getChatUnread } from '../../api/chat';
import { ApiError } from '../../api/client';
import styles from './Chat.module.css';

interface Props {
  orderId: number;
  /** `compact` — faqat ikonka (sarlavha qatori uchun), aks holda "Chat" yozuvi bilan. */
  variant?: 'default' | 'compact';
  label?: string;
  className?: string;
}

const POLL_MS = 30_000;

/**
 * Buyurtma chatiga kirish tugmasi (o'qilmaganlar badge'i bilan). Sender'ning
 * `OrderTrackingPage` va haydovchining `DriverActiveOrderPage` sahifalariga qo'yish
 * uchun mo'ljallangan — ikkalasida yo'l bir xil: `/orders/:id/chat`.
 *
 * Chat hali ochilmagan (buyurtma ACCEPTED bo'lmagan) yoki foydalanuvchi ishtirokchi
 * bo'lmasa server 404 qaytaradi — tugma umuman ko'rinmaydi. Badge har 30 s da va
 * sahifa qayta ko'ringanda yangilanadi.
 */
export function OpenChatButton({ orderId, variant = 'default', label = 'Chat', className }: Props) {
  const navigate = useNavigate();
  const [available, setAvailable] = useState(false);
  const [unread, setUnread] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const res = await getChatUnread(orderId);
      setAvailable(true);
      setUnread(res.unread_count);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setAvailable(false);
      // Boshqa xatolarda (tarmoq) oldingi holat qoladi.
    }
  }, [orderId]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [refresh]);

  if (!available) return null;

  return (
    <button
      type="button"
      className={`${styles.openBtn} ${variant === 'compact' ? styles.openBtnCompact : ''} ${className ?? ''}`}
      onClick={() => navigate(`/orders/${orderId}/chat`)}
      aria-label={unread > 0 ? `${label}: ${unread} ta o'qilmagan xabar` : label}
    >
      <span className={styles.openBtnIcon}>💬</span>
      {variant !== 'compact' && <span>{label}</span>}
      {unread > 0 && <span className={styles.badge}>{unread > 99 ? '99+' : unread}</span>}
    </button>
  );
}
