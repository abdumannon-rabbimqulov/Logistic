import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getUnreadSummary, useSupportEvents } from '../api/support';
import { BellIcon } from './icons';
import styles from './SupportBellButton.module.css';

// Murojaatlar (support) bo'limiga yagona kirish nuqtasi — ekranning yuqori o'ng
// burchagidagi qo'ng'iroq tugmasi. Pastki menyuda "Xabarlar" bandi yo'q
// (`BottomNav.tsx`), shuning uchun sender ko'radigan har bir asosiy ekranda shu
// tugma turishi kerak — aks holda bo'lim faqat bosh sahifadan ochilardi.
//
// Badge — javobi o'qilmagan murojaatlar soni (`GET /support/unread`). Support WS
// hodisasi kelganda qayta so'raladi (bir nechta hodisa ketma-ket kelsa — bitta so'rov).

export function SupportBellButton() {
  const navigate = useNavigate();
  const [unread, setUnread] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const refresh = useCallback(() => {
    getUnreadSummary()
      .then((s) => setUnread(s.tickets))
      .catch(() => undefined); // badge — ikkinchi darajali, xato ko'rsatilmaydi
  }, []);

  useEffect(() => {
    refresh();
    return () => clearTimeout(timer.current);
  }, [refresh]);

  useSupportEvents((event) => {
    if (event.type === 'message.created' || event.type === 'ticket.updated' || event.type === 'resync') {
      clearTimeout(timer.current);
      timer.current = setTimeout(refresh, 400);
    }
  });

  const label = unread > 0 ? `Murojaatlar, ${unread} ta o'qilmagan javob` : 'Murojaatlar';

  return (
    <button className={styles.iconCircle} onClick={() => navigate('/messages')} aria-label={label}>
      <BellIcon />
      {unread > 0 && (
        <span className={styles.badge} aria-hidden="true">
          {unread > 9 ? '9+' : unread}
        </span>
      )}
    </button>
  );
}
