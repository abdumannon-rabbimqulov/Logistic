import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../auth/AuthProvider';

// Backendda saqlangan manzillar uchun model/endpoint yo'q (tekshirildi) — V1 shunchaki
// qurilmada (localStorage) saqlanadi. Kelajakda serverga ko'chirish mumkin.

export interface SavedAddress {
  id: string;
  label: string;
  address: string;
  latitude: number;
  longitude: number;
}

// Kalit foydalanuvchiga bog'langan: bitta telefonda bir nechta Telegram akkaunt bo'lsa,
// localStorage umumiy — umumiy kalitda bir akkauntning manzillari boshqasiga ko'rinardi.
const LEGACY_KEY = 'yuk_saved_addresses';
const storageKey = (userId: number) => `yuk_saved_addresses:${userId}`;

function load(userId: number | null): SavedAddress[] {
  if (userId === null) return [];
  try {
    let raw = localStorage.getItem(storageKey(userId));
    if (raw === null) {
      // Eski (umumiy kalitli) ma'lumotni birinchi ochgan foydalanuvchiga bir marta ko'chiramiz.
      raw = localStorage.getItem(LEGACY_KEY);
      if (raw !== null) {
        localStorage.setItem(storageKey(userId), raw);
        localStorage.removeItem(LEGACY_KEY);
      }
    }
    return raw ? (JSON.parse(raw) as SavedAddress[]) : [];
  } catch {
    return [];
  }
}

export function useSavedAddresses() {
  const { userId } = useAuth();
  const [owner, setOwner] = useState<number | null>(userId);
  const [addresses, setAddresses] = useState<SavedAddress[]>(() => load(userId));

  // Foydalanuvchi o'zgarsa (logout/boshqa akkaunt) — uning ro'yxatini yuklaymiz.
  if (owner !== userId) {
    setOwner(userId);
    setAddresses(load(userId));
  }

  useEffect(() => {
    if (owner === null) return;
    try {
      localStorage.setItem(storageKey(owner), JSON.stringify(addresses));
    } catch {
      // saqlab bo'lmasa (xotira to'la/bloklangan) — ro'yxat faqat shu sessiyada qoladi
    }
  }, [owner, addresses]);

  const add = useCallback((entry: Omit<SavedAddress, 'id'>) => {
    setAddresses((prev) => [...prev, { ...entry, id: crypto.randomUUID() }]);
  }, []);

  const remove = useCallback((id: string) => {
    setAddresses((prev) => prev.filter((a) => a.id !== id));
  }, []);

  return { addresses, add, remove };
}
