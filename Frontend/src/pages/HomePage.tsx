import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { listMyOrders } from '../api/orders';
import { listTruckTypes } from '../api/truckTypes';
import { BottomNav } from '../components/BottomNav';
import { ChevronRightIcon, HomeAddressIcon, InfoIcon, PinIcon, PlusIcon, ProfileIcon, WorkAddressIcon, truckIconFor } from '../components/icons';
import { SupportBellButton } from '../components/SupportBellButton';
import { useSavedAddresses } from '../hooks/useSavedAddresses';
import type { OrderListItem, TruckType } from '../types/api';
import type { OrderPrefillState } from '../types/navigation';
import { formatPrice, formatRelativeDate, routeLabel } from '../utils/format';
import { orderStatusMeta } from '../utils/orderStatus';
import styles from './HomePage.module.css';

// PENDING ham faol: ilgari "haydovchi qidirilmoqda" buyurtmasi bosh sahifada umuman
// ko'rinmasdi va mijoz uni yo'qotib qo'ygandek his qilardi.
const ACTIVE_STATUSES = new Set(['PENDING', 'SCHEDULED', 'ACCEPTED', 'IN_PROGRESS']);
const PAST_STATUSES = new Set(['COMPLETED', 'CANCELLED']);

export function HomePage() {
  const navigate = useNavigate();
  const { addresses } = useSavedAddresses();
  const [truckTypes, setTruckTypes] = useState<TruckType[]>([]);
  const [activeOrder, setActiveOrder] = useState<OrderListItem | null>(null);
  const [activeCount, setActiveCount] = useState(0);
  const [recentOrders, setRecentOrders] = useState<OrderListItem[]>([]);
  const [ordersState, setOrdersState] = useState<'loading' | 'loaded' | 'error'>('loading');
  const [truckTypesState, setTruckTypesState] = useState<'loading' | 'loaded' | 'error'>('loading');
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setOrdersState((state) => state === 'loaded' ? 'loaded' : 'loading');
    setTruckTypesState((state) => state === 'loaded' ? 'loaded' : 'loading');
    // Ro'yxat yo'nalishlarni o'zi qaytaradi — buyurtma boshiga alohida so'rov kerak emas.
    const [typesResult, ordersResult] = await Promise.allSettled([listTruckTypes(), listMyOrders()]);
    if (currentRequest !== requestId.current) return;

    if (typesResult.status === 'fulfilled') {
      setTruckTypes(typesResult.value);
      setTruckTypesState('loaded');
    } else {
      setTruckTypesState('error');
    }

    if (ordersResult.status === 'fulfilled') {
      const orders = ordersResult.value;
      const active = orders.filter((o) => ACTIVE_STATUSES.has(o.status));
      setActiveOrder(active[0] ?? null);
      setActiveCount(active.length);
      setRecentOrders(orders.filter((o) => PAST_STATUSES.has(o.status)).slice(0, 3));
      setOrdersState('loaded');
    } else {
      setOrdersState('error');
    }
  }, []);

  useEffect(() => {
    document.title = 'Bosh sahifa · YUK';
    void load();
    // Ilovaga qaytilganda faol buyurtma holati yangilanadi.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      requestId.current += 1;
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [load]);

  function goToOrderScreen(prefill?: OrderPrefillState) {
    navigate('/order/new', { state: prefill });
  }

  const activeTruckType = activeOrder
    ? truckTypes.find((t) => t.id === activeOrder.required_truck_type_id)
    : undefined;
  const ActiveTruckIcon = truckIconFor(activeTruckType?.name ?? '');

  return (
    <div className={styles.page}>
      <div className={styles.scroll}>
        <div className={styles.topBar}>
          <div className={styles.wordmark}>YUK</div>
          <div className={styles.topActions}>
            <SupportBellButton />
            <button className={styles.iconCircle} onClick={() => navigate('/profile')} aria-label="Profil">
              <ProfileIcon />
            </button>
          </div>
        </div>

        <div className={styles.section}>
          <button className={styles.mainCta} onClick={() => goToOrderScreen()}>
            <div className={styles.mainCtaIcon}>
              <PinIcon />
            </div>
            <div className={styles.mainCtaText}>
              <div className={styles.mainCtaTitle}>Qayerga yuk jo'natasiz?</div>
              <div className={styles.mainCtaSubtitle}>Manzilni kiriting va bir necha soniyada narxni bilib oling</div>
            </div>
            <ChevronRightIcon />
          </button>
        </div>

        {ordersState === 'loading' && <div className={styles.inlineState} role="status">Buyurtmalar yuklanmoqda…</div>}
        {ordersState === 'error' && (
          <div className={styles.inlineError} role="alert">
            <span>Buyurtmalar yuklanmadi. Internet aloqasini tekshirib, qayta urinib ko‘ring.</span>
            <button type="button" className={styles.retryInline} onClick={() => void load()}>Qayta urinish</button>
          </div>
        )}

        {activeOrder && (
          <div className={styles.section}>
            <button className={styles.activeCard} onClick={() => navigate(`/orders/${activeOrder.id}`)}>
              <div className={styles.activeTop}>
                <div className={styles.activeStatus}>
                  <span className={styles.activeDot} />
                  <span>{orderStatusMeta(activeOrder.status).label}</span>
                </div>
                {activeCount > 1 && (
                  <span className={styles.activeMore}>
                    yana {activeCount - 1} ta faol
                  </span>
                )}
              </div>
              <div className={styles.activeBody}>
                <div className={styles.activeIconBox}>
                  <ActiveTruckIcon color="#fff" />
                </div>
                <div className={styles.activeInfo}>
                  <div className={styles.activeRoute}>
                    {routeLabel(activeOrder.origin?.address, activeOrder.destination?.address)}
                  </div>
                  <div className={styles.activeMeta}>{formatPrice(activeOrder.price)} {activeOrder.currency}</div>
                </div>
                <span className={styles.trackBtn}>Kuzatish</span>
              </div>
            </button>
          </div>
        )}

        {truckTypesState === 'loading' && <div className={styles.inlineState} role="status">Transport turlari yuklanmoqda…</div>}
        {truckTypesState === 'error' && (
          <div className={styles.inlineError} role="alert">
            <span>Transport turlari yuklanmadi.</span>
            <button type="button" className={styles.retryInline} onClick={() => void load()}>Qayta urinish</button>
          </div>
        )}
        {truckTypes.length > 0 && (
          <div style={{ paddingTop: 22 }}>
            <div className={styles.sectionTitle}>Transport turini tanlang</div>
            <div className={styles.transportScroll}>
              {truckTypes.map((t) => {
                const Icon = truckIconFor(t.name);
                return (
                  <button
                    key={t.id}
                    className={styles.transportItem}
                    onClick={() => goToOrderScreen({ truckTypeId: t.id })}
                  >
                    <div className={styles.transportIconBox}>
                      <Icon />
                    </div>
                    <span className={styles.transportLabel}>{t.name}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <div className={styles.section}>
          <div className={styles.sectionTitle} style={{ padding: 0 }}>
            Saqlangan manzillar
          </div>
          <div style={{ marginTop: 8 }}>
            {addresses.length === 0 && <div className={styles.emptyHint}>Hali saqlangan manzil yo'q</div>}
            {addresses.map((a) => (
              <button
                key={a.id}
                className={styles.addressRow}
                onClick={() =>
                  goToOrderScreen({
                    destination: { address: a.address, latitude: a.latitude, longitude: a.longitude },
                  })
                }
              >
                <div className={styles.addressIconBox}>
                  {a.label.toLowerCase().includes('ish') ? <WorkAddressIcon /> : <HomeAddressIcon />}
                </div>
                <div className={styles.addressInfo}>
                  <div className={styles.addressLabel}>{a.label}</div>
                  <div className={styles.addressSub}>{a.address}</div>
                </div>
              </button>
            ))}
            <button className={styles.addressRow} onClick={() => navigate('/order/new', { state: { openSaveAddress: true } })}>
              <div className={styles.addressIconBox}>
                <PlusIcon color="var(--color-text-primary)" />
              </div>
              <div className={styles.addressInfo}>
                <div className={styles.addressLabel}>Manzil qo'shish</div>
              </div>
            </button>
          </div>
        </div>

        {ordersState === 'loaded' && recentOrders.length === 0 && (
          <div className={styles.section}>
            <div className={styles.sectionTitle} style={{ padding: 0 }}>Oxirgi buyurtmalar</div>
            <div className={styles.emptyHint}>Yakunlangan buyurtmalar hozircha yo‘q.</div>
          </div>
        )}

        {recentOrders.length > 0 && (
          <div className={styles.section}>
            <div className={styles.sectionTitle} style={{ padding: 0 }}>
              Oxirgi buyurtmalar
            </div>
            <div className={styles.recentList}>
              {recentOrders.map((order) => {
                const truckType = truckTypes.find((t) => t.id === order.required_truck_type_id);
                return (
                  <div key={order.id} className={styles.recentCard}>
                    <div className={styles.recentInfo}>
                      <div className={styles.recentRoute}>
                        {routeLabel(order.origin?.address, order.destination?.address)}
                      </div>
                      <div className={styles.recentMeta}>
                        {formatRelativeDate(order.created_at)} · {truckType?.name ?? ''}
                      </div>
                    </div>
                    <button
                      className={styles.repeatBtn}
                      onClick={() =>
                        goToOrderScreen({
                          truckTypeId: order.required_truck_type_id ?? undefined,
                          origin: order.origin
                            ? { address: order.origin.address ?? '', latitude: Number(order.origin.latitude), longitude: Number(order.origin.longitude) }
                            : undefined,
                          destination: order.destination
                            ? {
                                address: order.destination.address ?? '',
                                latitude: Number(order.destination.latitude),
                                longitude: Number(order.destination.longitude),
                              }
                            : undefined,
                        })
                      }
                    >
                      Takrorlash
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        <div className={styles.section} style={{ paddingBottom: 24 }}>
          <div className={styles.banner}>
            <InfoIcon />
            <div className={styles.bannerText}>Yangi haydovchilar uchun tekshiruv kuchaytirildi — yukingiz xavfsiz qo'lda.</div>
          </div>
        </div>
      </div>

      <BottomNav />
    </div>
  );
}
