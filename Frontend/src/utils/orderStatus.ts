import type { OrderStatus, WaypointStatus, WaypointType } from '../types/api';

/** Rang guruhi — `components/OrderStatusBadge.module.css` dagi klasslar bilan mos. */
export type StatusTone = 'search' | 'planned' | 'active' | 'success' | 'danger';

export interface StatusMeta {
  /** Mijoz (sender) uchun tushunarli yorliq. */
  label: string;
  /** Neytral qisqa yorliq — haydovchi va admin ekranlari uchun. */
  short: string;
  /** Mijozga bir jumlada: hozir nima bo'lyapti. */
  hint: string;
  tone: StatusTone;
}

/**
 * Buyurtma statuslarining YAGONA ro'yxati (yorliq, izoh, rang). Ilgari yorliqlar
 * 5 ta faylda alohida-alohida yozilgan va bir-biridan farq qilardi.
 */
export const ORDER_STATUS_META: Record<OrderStatus, StatusMeta> = {
  PENDING: { label: 'Haydovchi qidirilmoqda', short: "Qidirilmoqda", hint: 'Mos haydovchilarga taklif yuborilmoqda', tone: 'search' },
  SCHEDULED: {
    label: 'Rejalashtirilgan', short: "Rejalashtirilgan",
    hint: 'Haydovchi biriktirilgan, yuklash vaqtini kutmoqda',
    tone: 'planned',
  },
  ACCEPTED: { label: 'Haydovchi topildi', short: "Qabul qilindi", hint: 'Haydovchi yuk olish nuqtasiga kelmoqda', tone: 'active' },
  IN_PROGRESS: { label: "Yo'lda", short: "Yo'lda", hint: 'Yuk yetkazish manziliga olib ketilmoqda', tone: 'active' },
  COMPLETED: { label: 'Yetkazildi', short: "Yakunlandi", hint: 'Buyurtma muvaffaqiyatli yakunlandi', tone: 'success' },
  CANCELLED: { label: 'Bekor qilindi', short: "Bekor qilindi", hint: 'Buyurtma bekor qilingan', tone: 'danger' },
};

export function orderStatusMeta(status: string): StatusMeta {
  return (
    ORDER_STATUS_META[status as OrderStatus] ?? { label: status, short: status, hint: '', tone: 'planned' }
  );
}

export const WAYPOINT_STATUS_LABEL: Record<WaypointStatus, string> = {
  PENDING: 'Kutilmoqda',
  ARRIVED: 'Yetib keldi',
  COMPLETED: 'Yakunlandi',
  SKIPPED: 'O‘tkazib yuborildi',
};

export const WAYPOINT_TYPE_LABEL: Record<WaypointType, string> = {
  PICKUP: 'Yuk ortish',
  DELIVERY: 'Yetkazish',
  TRANSIT: 'Oraliq nuqta',
};

/** Holati boshqa o'zgarmaydigan buyurtmalar. */
export const FINAL_ORDER_STATUSES: ReadonlySet<string> = new Set(['COMPLETED', 'CANCELLED']);
