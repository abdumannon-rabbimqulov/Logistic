import type { OrderDetail, OrderWaypoint } from '../types/api';
import styles from './OrderStepper.module.css';

interface Step {
  key: string;
  label: string;
  time?: string | null;
}

function formatTime(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleString('uz-UZ', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const isDone = (wp: OrderWaypoint | undefined) =>
  wp != null && (wp.status === 'COMPLETED' || wp.status === 'SKIPPED');

/**
 * Buyurtmaning qaysi bosqichda ekani — mijoz uchun yagona tushunarli ko'rinish.
 * Bosqich order statusi va nuqtalar holatidan hisoblanadi (backend o'zgarmaydi):
 * birinchi PICKUP "yetib keldi" bo'lsa — yuk ortilmoqda, yopilsa — yo'lda va h.k.
 *
 * Qaytaradi: bosqichlar ro'yxati va joriy bosqich indeksi (hammasi tugagan bo'lsa
 * `steps.length`).
 */
function computeOrderSteps(order: OrderDetail): { steps: Step[]; current: number } {
  const pickup = order.waypoints.find((w) => w.type === 'PICKUP') ?? order.waypoints[0];
  const lastDelivery = [...order.waypoints].reverse().find((w) => w.type === 'DELIVERY');

  const steps: Step[] = [
    { key: 'created', label: 'Buyurtma berildi', time: formatTime(order.created_at) },
    { key: 'search', label: 'Haydovchi qidirilmoqda' },
    { key: 'found', label: 'Haydovchi topildi' },
    { key: 'started', label: "Haydovchi yo'lga chiqdi", time: formatTime(order.started_at) },
    { key: 'loading', label: 'Yuk ortilmoqda', time: formatTime(pickup?.arrived_at) },
    { key: 'transit', label: "Yo'lda", time: formatTime(pickup?.completed_at) },
    {
      key: 'delivered',
      label: 'Yetkazildi',
      time: formatTime(order.completed_at ?? lastDelivery?.completed_at),
    },
  ];

  let current: number;
  if (order.status === 'COMPLETED') current = steps.length;
  else if (isDone(pickup)) current = 5;
  else if (pickup?.status === 'ARRIVED') current = 4;
  else if (order.started_at) current = 3;
  else if (order.driver_id != null) current = 2;
  else current = 1;

  return { steps, current };
}

interface Props {
  order: OrderDetail;
}

export function OrderStepper({ order }: Props) {
  const { steps, current } = computeOrderSteps(order);
  const cancelled = order.status === 'CANCELLED';
  // Bekor qilinganda erishilgan bosqichlar ko'rsatiladi va oxiriga qizil yakun qo'shiladi.
  const visible = cancelled ? steps.slice(0, Math.max(1, current)) : steps;

  return (
    <ol className={styles.stepper} aria-label="Buyurtma bosqichlari">
      {visible.map((step, i) => {
        const state = i < current ? 'done' : i === current && !cancelled ? 'current' : 'todo';
        return (
          <li key={step.key} className={`${styles.step} ${styles[state]}`}>
            <span className={styles.marker} aria-hidden="true">
              {state === 'done' ? '✓' : ''}
            </span>
            <div className={styles.body}>
              <span className={styles.label}>
                {step.label}
                {state === 'current' && <span className={styles.srOnly}> (hozirgi bosqich)</span>}
              </span>
              {step.time && state === 'done' && <span className={styles.time}>{step.time}</span>}
            </div>
          </li>
        );
      })}
      {cancelled && (
        <li className={`${styles.step} ${styles.cancelled}`}>
          <span className={styles.marker} aria-hidden="true">
            ✕
          </span>
          <div className={styles.body}>
            <span className={styles.label}>Bekor qilindi</span>
            {order.cancelled_at && <span className={styles.time}>{formatTime(order.cancelled_at)}</span>}
          </div>
        </li>
      )}
    </ol>
  );
}
