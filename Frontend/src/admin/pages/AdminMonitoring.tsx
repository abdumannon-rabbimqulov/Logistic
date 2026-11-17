import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { getMonitoring } from '../../api/admin';
import { ApiError } from '../../api/client';
import type {
  HealthStatus,
  MonitoringComponentBase,
  MonitoringErrorEntry,
  MonitoringOverview,
  MonitoringRequests,
  MonitoringQueueRow,
  MonitoringRouteRow,
} from '../../types/api';
import { DataTable, type Column } from '../components/DataTable';
import { LineChart, type LinePoint } from '../components/LineChart';
import shared from '../shared.module.css';
import styles from './AdminMonitoring.module.css';

// Server monitoringi: holat, yuklama, so'rovlar tezligi va xatolari, navbatlar.
// Ma'lumot manbai — GET /system/monitoring (services/monitoring.py, services/metrics.py).

const RANGES = [
  { minutes: 15, label: '15 daq' },
  { minutes: 60, label: '1 soat' },
  { minutes: 360, label: '6 soat' },
  { minutes: 1440, label: '24 soat' },
] as const;

const REFRESH_MS = 15_000;

// ── Formatlash ──────────────────────────────────────────────────────────────

function fmtBytes(b?: number | null): string {
  if (b == null) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = b;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function fmtDuration(sec?: number | null): string {
  if (sec == null) return '—';
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d) return `${d} kun ${h} soat`;
  if (h) return `${h} soat ${m} daq`;
  return `${m} daq`;
}

function fmtMs(v?: number | null): string {
  if (v == null) return '—';
  if (v === 0) return '0 ms';
  if (v >= 1000) return `${(v / 1000).toFixed(2)} s`;
  // Ping kabi juda kichik qiymatlar "0 ms" bo'lib ko'rinmasin.
  return v < 10 ? `${v.toFixed(1)} ms` : `${Math.round(v)} ms`;
}

function fmtNum(v?: number | null, digits = 0): string {
  if (v == null) return '—';
  return v.toLocaleString('uz-UZ', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function fmtClock(t: number, withDate: boolean): string {
  const d = new Date(t * 1000);
  const hm = d.toLocaleTimeString('uz-UZ', { hour: '2-digit', minute: '2-digit' });
  return withDate ? `${d.toLocaleDateString('uz-UZ', { day: '2-digit', month: '2-digit' })} ${hm}` : hm;
}

// ── Holat belgisi: rang + ikonka + matn (rang hech qachon yolg'iz emas) ──────

const STATUS_META: Record<HealthStatus, { label: string; icon: string }> = {
  ok: { label: 'Ishlayapti', icon: '✓' },
  warn: { label: 'Diqqat', icon: '!' },
  critical: { label: 'Nosoz', icon: '✕' },
};

function StatusPill({ status }: { status: HealthStatus }) {
  const meta = STATUS_META[status];
  return (
    <span className={`${styles.pill} ${styles[`pill_${status}`]}`}>
      <span className={styles.pillIcon} aria-hidden>
        {meta.icon}
      </span>
      {meta.label}
    </span>
  );
}

function ComponentCard({
  title,
  status,
  children,
}: {
  title: string;
  status: HealthStatus;
  children: ReactNode;
}) {
  return (
    <div className={`${styles.compCard} ${styles[`comp_${status}`]}`}>
      <div className={styles.compHead}>
        <span className={styles.compTitle}>{title}</span>
        <StatusPill status={status} />
      </div>
      <div className={styles.compBody}>{children}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.statValue}>{value}</span>
    </div>
  );
}

function Meter({ label, percent, detail }: { label: string; percent?: number | null; detail: string }) {
  const p = percent ?? 0;
  const level: HealthStatus = p >= 90 ? 'critical' : p >= 80 ? 'warn' : 'ok';
  return (
    <div className={styles.meter}>
      <div className={styles.meterHead}>
        <span className={styles.statLabel}>{label}</span>
        <span className={styles.meterValue}>{percent != null ? `${percent.toFixed(0)}%` : '—'}</span>
      </div>
      <div
        className={styles.meterTrack}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={p}
      >
        <div className={`${styles.meterFill} ${styles[`fill_${level}`]}`} style={{ width: `${Math.min(p, 100)}%` }} />
      </div>
      <span className={styles.meterDetail}>{detail}</span>
    </div>
  );
}

// ── Jadvallar ───────────────────────────────────────────────────────────────

const routeColumns: Column<MonitoringRouteRow>[] = [
  { key: 'route', header: 'Endpoint', render: (r) => <span className={shared.mono}>{r.route}</span> },
  { key: 'count', header: "So'rovlar", align: 'right', render: (r) => fmtNum(r.count) },
  { key: 'avg', header: "O'rtacha", align: 'right', render: (r) => fmtMs(r.avg_ms) },
  {
    key: 'e4',
    header: '4xx',
    align: 'right',
    render: (r) => (r.errors_4xx ? fmtNum(r.errors_4xx) : '—'),
  },
  {
    key: 'e5',
    header: '5xx',
    align: 'right',
    render: (r) =>
      r.errors_5xx ? <strong className={styles.errText}>{fmtNum(r.errors_5xx)}</strong> : '—',
  },
];

// ── Muammo bosilganda ochiladigan tafsilot ──────────────────────────────────
// Faqat API muammolarida tafsilot bor: qaysi endpoint xato bergani va nima uchun
// (oxirgi xatolar ro'yxati), yoki qaysi endpointlar sekin.

function issueDetail(name: string, text: string, req: MonitoringRequests): ReactNode | null {
  if (name !== 'api') return null;
  if (text.includes('5xx')) {
    const routes = req.error_routes.filter((r) => r.errors_5xx > 0);
    const errors = (req.recent_errors ?? []).filter((e) => e.status >= 500);
    return (
      <>
        {routes.length > 0 && (
          <DataTable columns={routeColumns} rows={routes} rowKey={(r) => r.route} emptyText="" />
        )}
        <RecentErrors errors={errors} />
      </>
    );
  }
  if (text.startsWith('Sekin')) {
    return (
      <DataTable
        columns={routeColumns}
        rows={req.slowest_routes.slice(0, 5)}
        rowKey={(r) => r.route}
        emptyText="So'rov yo'q"
      />
    );
  }
  return null;
}

function RecentErrors({ errors }: { errors: MonitoringErrorEntry[] }) {
  if (!errors.length) {
    return (
      <div className={styles.issueEmpty}>
        Xato matni saqlanmagan (bu funksiya qo'shilishidan oldingi xato bo'lishi mumkin).
      </div>
    );
  }
  return (
    <ul className={styles.errorList}>
      {errors.map((e) => (
        <li key={`${e.request_id}-${e.ts}`} className={styles.errorItem}>
          <div className={styles.errorHead}>
            <span className={shared.mono}>
              {e.method} {e.path}
            </span>
            <span className={styles.errorMeta}>
              {e.status} · {e.exc_type} · {new Date(e.ts * 1000).toLocaleString('uz-UZ')}
            </span>
          </div>
          <div className={styles.errorMsg}>{e.message}</div>
          <div className={styles.errorMeta}>request_id: {e.request_id}</div>
        </li>
      ))}
    </ul>
  );
}

const queueColumns: Column<MonitoringQueueRow>[] = [
  { key: 'queue', header: 'Navbat', render: (r) => <span className={shared.mono}>{r.queue}</span> },
  { key: 'consumer', header: "Kim o'qiydi", render: (r) => r.consumer },
  { key: 'messages', header: 'Kutayotgan', align: 'right', render: (r) => fmtNum(r.messages) },
  { key: 'consumers', header: "O'quvchilar", align: 'right', render: (r) => fmtNum(r.consumers) },
  { key: 'status', header: 'Holat', render: (r) => <StatusPill status={r.status} /> },
];

const COMPONENT_LABELS: Record<string, string> = {
  api: 'API',
  server: 'Server',
  postgres: 'PostgreSQL',
  redis: 'Redis',
  rabbitmq: 'RabbitMQ',
  osrm: 'OSRM (marshrut)',
  support: 'Support xizmati',
  business: 'Buyurtmalar oqimi',
};

// ── Sahifa ──────────────────────────────────────────────────────────────────

export function AdminMonitoring() {
  const [minutes, setMinutes] = useState<number>(60);
  const [data, setData] = useState<MonitoringOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [auto, setAuto] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const reqId = useRef(0);
  const [openIssue, setOpenIssue] = useState<string | null>(null);

  const load = useCallback(async () => {
    const id = ++reqId.current;
    setLoading(true);
    try {
      const res = await getMonitoring(minutes);
      if (id !== reqId.current) return; // eskirgan javob (oraliq o'zgargan)
      setData(res);
      setError(null);
      setUpdatedAt(new Date());
    } catch (err) {
      if (id !== reqId.current) return;
      setError(err instanceof ApiError ? err.message : "Monitoring ma'lumotini olib bo'lmadi");
    } finally {
      if (id === reqId.current) setLoading(false);
    }
  }, [minutes]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!auto) return;
    // Tab ko'rinmayotganda so'ramaymiz — fonda ochiq qolgan sahifa serverni bekorga yuklamasin.
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [auto, load]);

  const c = data?.components;
  const req = data?.requests;
  const withDate = minutes > 360;
  const series = req?.series ?? [];
  const pts = (pick: (p: (typeof series)[number]) => number | null): LinePoint[] =>
    series.map((p) => ({ t: p.t, v: pick(p) }));
  const allIssues = c
    ? (Object.entries(c) as [string, MonitoringComponentBase][]).flatMap(([name, comp]) =>
        comp.issues.map((text) => ({ name, text, status: comp.status })),
      )
    : [];
  const stepNote = req && req.step_minutes > 1 ? `Har nuqta — ${req.step_minutes} daqiqa` : undefined;
  const tf = (t: number) => fmtClock(t, withDate);

  return (
    <div className={shared.page}>
      <div className={shared.pageHead}>
        <div>
          <h1 className={shared.pageTitle}>Server</h1>
          <div className={shared.pageSub}>
            Yuklama, so'rovlar tezligi va xatolari, navbatlar va xizmatlar holati
          </div>
        </div>

        <div className={styles.controls}>
          <div className={styles.segmented} role="group" aria-label="Vaqt oralig'i">
            {RANGES.map((r) => (
              <button
                key={r.minutes}
                className={minutes === r.minutes ? styles.segActive : styles.seg}
                aria-pressed={minutes === r.minutes}
                onClick={() => setMinutes(r.minutes)}
              >
                {r.label}
              </button>
            ))}
          </div>
          <label className={styles.autoToggle}>
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
            Avto (15s)
          </label>
          <button className={shared.ghostBtn} onClick={() => void load()} disabled={loading}>
            {loading ? 'Yuklanmoqda…' : 'Yangilash'}
          </button>
        </div>
      </div>

      {error && <div className={shared.errorBanner}>{error}</div>}

      {!data && !error && <div className={styles.skeleton} />}

      {data && c && req && (
        <>
          {/* ── Umumiy holat va muammolar ro'yxati ── */}
          <section className={`${styles.banner} ${styles[`banner_${data.status}`]}`}>
            <div className={styles.bannerHead}>
              <StatusPill status={data.status} />
              <span className={styles.bannerTitle}>
                {data.status === 'ok'
                  ? 'Hamma tizimlar normal ishlayapti'
                  : `${allIssues.length} ta muammo aniqlandi`}
              </span>
              {updatedAt && (
                <span className={styles.updated}>
                  Yangilandi: {updatedAt.toLocaleTimeString('uz-UZ')}
                </span>
              )}
            </div>
            {allIssues.length > 0 && (
              <ul className={styles.issues}>
                {allIssues.map((i) => {
                  const key = `${i.name}:${i.text}`;
                  const label = (
                    <>
                      <strong>{COMPONENT_LABELS[i.name] ?? i.name}:</strong> {i.text}
                    </>
                  );
                  const detail = issueDetail(i.name, i.text, req);
                  if (!detail) return <li key={key}>{label}</li>;
                  // Matn har 15s yangilanadi (masalan foiz o'zgaradi) — ochiq holat
                  // komponent nomi + muammo turiga bog'lanadi, to'liq matnga emas.
                  const openKey = `${i.name}:${i.text.includes('5xx') ? '5xx' : 'slow'}`;
                  const open = openIssue === openKey;
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        className={styles.issueToggle}
                        aria-expanded={open}
                        onClick={() => setOpenIssue(open ? null : openKey)}
                      >
                        {label}
                        <span className={styles.issueHint}>{open ? 'Yopish ▴' : 'Batafsil ▾'}</span>
                      </button>
                      {open && <div className={styles.issueDetail}>{detail}</div>}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {/* ── Xizmatlar holati ── */}
          <section className={styles.compGrid}>
            <ComponentCard title="API" status={c.api.status}>
              <Stat label="Hozir bajarilmoqda" value={fmtNum(c.api.in_flight)} />
              <Stat
                label="DB ulanish puli"
                value={c.api.db_pool ? `${c.api.db_pool.checked_out} / ${c.api.db_pool.size}` : '—'}
              />
              <Stat label="Jarayon xotirasi" value={fmtBytes(c.api.process_rss)} />
              <Stat label="Ishlash vaqti" value={fmtDuration(c.api.process_uptime_sec)} />
            </ComponentCard>
            <ComponentCard title="PostgreSQL" status={c.postgres.status}>
              <Stat label="Ping" value={fmtMs(c.postgres.ping_ms)} />
              <Stat
                label="Ulanishlar"
                value={`${fmtNum(c.postgres.connections)} / ${fmtNum(c.postgres.max_connections)}`}
              />
              <Stat label="Kesh hit" value={c.postgres.cache_hit_percent != null ? `${c.postgres.cache_hit_percent}%` : '—'} />
              <Stat label="Eng uzun so'rov" value={c.postgres.longest_query_sec != null ? `${c.postgres.longest_query_sec}s` : '—'} />
            </ComponentCard>
            <ComponentCard title="Redis" status={c.redis.status}>
              <Stat label="Ping" value={fmtMs(c.redis.ping_ms)} />
              <Stat label="Xotira" value={fmtBytes(c.redis.used_memory)} />
              <Stat label="Amal/s" value={fmtNum(c.redis.ops_per_sec)} />
              <Stat label="Klientlar" value={fmtNum(c.redis.connected_clients)} />
            </ComponentCard>
            <ComponentCard title="RabbitMQ va worker'lar" status={c.rabbitmq.status}>
              <Stat label="dispatch-worker" value={workerLabel(c.rabbitmq.workers?.['dispatch-worker'])} />
              <Stat label="events-worker" value={workerLabel(c.rabbitmq.workers?.['events-worker'])} />
              <Stat
                label="Dispatch navbati"
                value={fmtNum(c.rabbitmq.queues?.find((q) => q.queue === 'dispatch.jobs')?.messages)}
              />
              <Stat
                label="Yo'qolgan vazifalar"
                value={fmtNum(c.rabbitmq.queues?.find((q) => q.queue === 'dispatch.dead')?.messages)}
              />
            </ComponentCard>
            <ComponentCard title="Buyurtmalar oqimi" status={c.business.status}>
              <Stat label="Haydovchi qidirilmoqda" value={fmtNum(c.business.orders_searching)} />
              <Stat label="Qotib qolgan" value={fmtNum(c.business.orders_stuck)} />
              <Stat label="Narx kutilmoqda" value={fmtNum(c.business.orders_waiting_price)} />
              <Stat label="Yangi (1 soat)" value={fmtNum(c.business.orders_created_last_hour)} />
            </ComponentCard>
            <ComponentCard title="Tashqi xizmatlar" status={worstOf(c.osrm.status, c.support.status)}>
              <Stat label="OSRM javobi" value={fmtMs(c.osrm.latency_ms)} />
              <Stat label="OSRM holati" value={<StatusPill status={c.osrm.status} />} />
              <Stat label="Support javobi" value={fmtMs(c.support.latency_ms)} />
              <Stat label="Support holati" value={<StatusPill status={c.support.status} />} />
            </ComponentCard>
          </section>

          {/* ── So'rovlar: asosiy ko'rsatkichlar ── */}
          <section className={styles.kpiRow}>
            <Kpi label="So'rovlar" value={fmtNum(req.totals.requests)} sub={`${fmtNum(req.totals.rpm, 1)} / daqiqa`} />
            <Kpi label="Javob vaqti p50" value={fmtMs(req.totals.p50_ms)} sub={`o'rtacha ${fmtMs(req.totals.avg_ms)}`} />
            <Kpi label="Javob vaqti p95" value={fmtMs(req.totals.p95_ms)} sub={`p99 ${fmtMs(req.totals.p99_ms)}`} />
            <Kpi
              label="Server xatolari (5xx)"
              value={fmtNum(req.totals.errors_5xx)}
              sub={`${req.totals.error_rate_5xx}% so'rovlardan`}
            />
            <Kpi label="Mijoz xatolari (4xx)" value={fmtNum(req.totals.errors_4xx)} sub="401, 403, 404, 422…" />
          </section>

          {/* ── Grafiklar ── */}
          <section className={styles.chartGrid}>
            <LineChart
              title="So'rovlar / daqiqa"
              points={pts((p) => p.rpm)}
              formatValue={(v) => fmtNum(v, 1)}
              formatTime={tf}
              note={stepNote}
            />
            <LineChart
              title="Javob vaqti p95"
              points={pts((p) => p.p95_ms)}
              formatValue={fmtMs}
              formatTime={tf}
              note="95% so'rovlar shundan tezroq javob oldi"
            />
            <LineChart
              title="Server xatolari (5xx)"
              points={pts((p) => p.errors_5xx)}
              formatValue={(v) => fmtNum(v, 1)}
              formatTime={tf}
              note="Har biri — foydalanuvchi uchun bajarilmay qolgan so'rov"
            />
            <LineChart
              title="Mijoz xatolari (4xx)"
              points={pts((p) => p.errors_4xx)}
              formatValue={(v) => fmtNum(v, 1)}
              formatTime={tf}
            />
          </section>

          {/* ── Server resurslari ── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>Server resurslari</h2>
              <StatusPill status={c.server.status} />
            </div>
            <div className={styles.meters}>
              <Meter label="CPU" percent={c.server.cpu_percent} detail={`${c.server.cpu_cores ?? '—'} yadro`} />
              <Meter
                label="RAM"
                percent={c.server.mem_percent}
                detail={`${fmtBytes(c.server.mem_used)} / ${fmtBytes(c.server.mem_total)}`}
              />
              <Meter
                label="Disk"
                percent={c.server.disk_percent}
                detail={`${fmtBytes(c.server.disk_used)} / ${fmtBytes(c.server.disk_total)}`}
              />
              <Meter
                label="Swap"
                percent={c.server.swap_total ? ((c.server.swap_used ?? 0) / c.server.swap_total) * 100 : null}
                detail={`${fmtBytes(c.server.swap_used)} / ${fmtBytes(c.server.swap_total)}`}
              />
            </div>
            <div className={styles.statRow}>
              <Stat
                label="Load average (1 / 5 / 15 daq)"
                value={c.server.load_avg ? c.server.load_avg.map((v) => v.toFixed(2)).join(' / ') : '—'}
              />
              <Stat label="Server ishlash vaqti" value={fmtDuration(c.server.uptime_sec)} />
              <Stat label="Baza hajmi" value={fmtBytes(c.postgres.size_bytes)} />
              <Stat label="Deadlock'lar (jami)" value={fmtNum(c.postgres.deadlocks)} />
            </div>
          </section>

          {/* ── Javob vaqti taqsimoti ── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>Javob vaqti taqsimoti</h2>
              <span className={styles.panelSub}>Tanlangan oraliqdagi barcha so'rovlar</span>
            </div>
            <Histogram edges={req.bucket_edges_ms} counts={req.totals.histogram} />
          </section>

          {/* ── Endpointlar ── */}
          <section className={styles.tableGrid}>
            <div className={styles.panel}>
              <div className={styles.panelHead}>
                <h2 className={styles.panelTitle}>Eng sekin endpointlar</h2>
                <span className={styles.panelSub}>kamida 3 so'rov</span>
              </div>
              <DataTable columns={routeColumns} rows={req.slowest_routes} rowKey={(r) => r.route} emptyText="So'rov yo'q" />
            </div>
            <div className={styles.panel}>
              <div className={styles.panelHead}>
                <h2 className={styles.panelTitle}>Xato qaytargan endpointlar</h2>
              </div>
              <DataTable columns={routeColumns} rows={req.error_routes} rowKey={(r) => r.route} emptyText="Xato yo'q ✓" />
            </div>
          </section>

          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>Eng ko'p chaqirilgan endpointlar</h2>
            </div>
            <DataTable columns={routeColumns} rows={req.busiest_routes} rowKey={(r) => r.route} emptyText="So'rov yo'q" />
          </section>

          {/* ── Navbatlar ── */}
          <section className={styles.panel}>
            <div className={styles.panelHead}>
              <h2 className={styles.panelTitle}>RabbitMQ navbatlari</h2>
              <span className={styles.panelSub}>
                O'quvchisi 0 bo'lsa — worker ishlamayapti; dispatch.dead — bajarilmay qolgan vazifalar
              </span>
            </div>
            <DataTable
              columns={queueColumns}
              rows={c.rabbitmq.queues ?? []}
              rowKey={(r) => r.queue}
              emptyText="RabbitMQ ma'lumoti yo'q"
            />
          </section>

          <p className={styles.footnote}>
            Bot va worker jarayonlari HTTP so'rov qabul qilmagani uchun ular so'rov statistikasida yo'q;
            worker'lar navbatdagi o'quvchilar soni orqali kuzatiladi. Ma'lumotlar 26 soat saqlanadi.
          </p>
        </>
      )}
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className={styles.kpi}>
      <span className={styles.statLabel}>{label}</span>
      <span className={styles.kpiValue}>{value}</span>
      {sub && <span className={styles.kpiSub}>{sub}</span>}
    </div>
  );
}

function workerLabel(consumers?: number | null): ReactNode {
  if (consumers == null) return '—';
  return consumers > 0 ? (
    <span>{consumers} ta ishlayapti</span>
  ) : (
    <strong className={styles.errText}>ishlamayapti</strong>
  );
}

function worstOf(...s: HealthStatus[]): HealthStatus {
  return s.includes('critical') ? 'critical' : s.includes('warn') ? 'warn' : 'ok';
}

/** Gistogramma: har bo'lak — gorizontal ustun, qiymati va ulushi yonida yozilgan
 *  (10 ta bo'lak — hammasiga yorliq sig'adi, tooltip shart emas). */
function Histogram({ edges, counts }: { edges: number[]; counts: number[] }) {
  const total = counts.reduce((a, b) => a + b, 0);
  const max = Math.max(1, ...counts);
  const labels = counts.map((_, i) => {
    if (i === 0) return `≤ ${fmtMs(edges[0])}`;
    if (i >= edges.length) return `> ${fmtMs(edges[edges.length - 1])}`;
    return `${fmtMs(edges[i - 1])} – ${fmtMs(edges[i])}`;
  });
  if (!total) return <div className={styles.empty}>Bu oraliqda so'rov yo'q</div>;
  return (
    <div className={styles.hist}>
      {counts.map((n, i) => (
        <div key={i} className={styles.histRow}>
          <span className={styles.histLabel}>{labels[i]}</span>
          <div className={styles.histTrack}>
            <div className={styles.histBar} style={{ width: `${(n / max) * 100}%` }} />
          </div>
          <span className={styles.histValue}>
            {fmtNum(n)} <span className={styles.histPct}>({((n / total) * 100).toFixed(1)}%)</span>
          </span>
        </div>
      ))}
    </div>
  );
}
