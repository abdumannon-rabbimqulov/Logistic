import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getTelegramWebApp } from '../../telegram';

// Telegram bildirishnomasidagi "Chatni ochish" tugmasi mini-app'ni
// `?startapp=chat_<orderId>` bilan ochadi (workers/chat_notify.py). Telegram bu
// qiymatni `initDataUnsafe.start_param` (va URL'da `tgWebAppStartParam`) sifatida
// beradi. Ilova ochilganda bir marta o'qib, chat sahifasiga o'tamiz.
//
// Modul darajasidagi bayroq: foydalanuvchi chatdan orqaga qaytganda (komponent
// qayta mount bo'lsa ham) yana chatga otib yuborilmasin.

let handled = false;

const START_RE = /^chat_(\d+)$/;

export function readChatStartParam(): number | null {
  const fromTelegram = getTelegramWebApp()?.initDataUnsafe.start_param;
  const params = new URLSearchParams(window.location.search);
  const raw = fromTelegram || params.get('tgWebAppStartParam') || params.get('startapp') || '';
  const match = START_RE.exec(raw);
  return match ? Number(match[1]) : null;
}

export function useChatDeepLink(): void {
  const navigate = useNavigate();
  useEffect(() => {
    if (handled) return;
    handled = true;
    const orderId = readChatStartParam();
    if (orderId) navigate(`/orders/${orderId}/chat`);
  }, [navigate]);
}
