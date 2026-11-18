import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { listMyOrders } from '../api/orders';
import { BottomNav } from '../components/BottomNav';
import { OrderStatusBadge } from '../components/OrderStatusBadge';
import { SupportBellButton } from '../components/SupportBellButton';
import type { OrderListItem } from '../types/api';
import { formatPrice, formatRelativeDate, routeLabel } from '../utils/format';
import styles from './OrdersListPage.module.css';

export function OrdersListPage() {
  const navigate = useNavigate();
  const [orders, setOrders] = useState<OrderListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    listMyOrders()
      .then(setOrders)
      // Xato "buyurtma yo'q" deb ko'rsatilmaydi — mijoz buyurtmasi yo'qolgan deb o'ylardi.
      .catch((err) => setError(err instanceof ApiError ? err.message : "Buyurtmalar yuklanmadi"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className={styles.page}>
      <div className={styles.topBar}>
        <div className={styles.title}>Buyurtmalar</div>
        <SupportBellButton />
      </div>

      {error && (
        <div className={styles.empty} role="alert">
          <div>{error}</div>
          <button className={styles.retryBtn} onClick={load}>
            Qayta urinish
          </button>
        </div>
      )}
      {!error && orders === null && <div className={styles.empty}>Yuklanmoqda...</div>}
      {!error && orders?.length === 0 && <div className={styles.empty}>Hali buyurtmalar yo'q</div>}

      <div className={styles.list}>
        {orders?.map((order) => (
          <button key={order.id} className={styles.card} onClick={() => navigate(`/orders/${order.id}`)}>
            <div className={styles.cardMain}>
              <div className={styles.cardTop}>
                <span className={styles.cargoName}>{order.cargo_name}</span>
                <OrderStatusBadge status={order.status} />
              </div>
              <div className={styles.route}>
                {routeLabel(order.origin?.address, order.destination?.address)}
              </div>
              <div className={styles.meta}>
                {formatRelativeDate(order.created_at)} · {formatPrice(order.price)} {order.currency}
              </div>
            </div>
          </button>
        ))}
      </div>

      <BottomNav />
    </div>
  );
}
