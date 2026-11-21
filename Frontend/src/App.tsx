import { lazy, Suspense } from 'react';
import { matchPath, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import styles from './App.module.css';
import { AuthProvider, useAuth } from './auth/AuthProvider';
import { getAccessToken } from './api/client';
import { useChatDeepLink } from './components/chat/useChatDeepLink';
import { HomePage } from './pages/HomePage';
import { LiveMapPage } from './pages/LiveMapPage';
import { LocalLoginPage } from './pages/LocalLoginPage';
import { OrderChatPage } from './pages/OrderChatPage';
import { OrderPage } from './pages/OrderPage';
import { SupportChatPage } from './pages/SupportChatPage';
import { OrderTrackingPage } from './pages/OrderTrackingPage';
import { OrdersListPage } from './pages/OrdersListPage';
import { ProfilePage } from './pages/ProfilePage';
import { RegisterPage } from './pages/RegisterPage';
import { PublicLandingPage } from './pages/PublicLandingPage';
import { getInitData } from './telegram';
import { LogoutButton } from './components/LogoutButton';

const AdminApp = lazy(() => import('./admin/AdminApp').then(({ AdminApp }) => ({ default: AdminApp })));
const ManagerApp = lazy(() => import('./manager/ManagerApp').then(({ ManagerApp }) => ({ default: ManagerApp })));
const DriverGate = lazy(() => import('./pages/DriverGate').then(({ DriverGate }) => ({ default: DriverGate })));

function LoadingScreen() {
  return <div className={styles.centerScreen}><div className={styles.spinner} role="status" aria-label="Yuklanmoqda" /></div>;
}

function SenderApp() {
  // Telegram'dagi "Chatni ochish" (`startapp=chat_<id>`) — chat sahifasiga o'tish.
  useChatDeepLink();
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/order/new" element={<OrderPage />} />
      <Route path="/orders" element={<OrdersListPage />} />
      <Route path="/orders/:orderId" element={<OrderTrackingPage />} />
      <Route path="/orders/:orderId/chat" element={<OrderChatPage />} />
      <Route path="/map" element={<LiveMapPage role="sender" />} />
      {/* Yordam xizmati — har foydalanuvchiga bitta chat. Eski `/messages/:id` havolalari ham shu yerga. */}
      <Route path="/messages" element={<SupportChatPage />} />
      <Route path="/messages/:ticketId" element={<Navigate to="/messages" replace />} />
      <Route path="/profile" element={<ProfilePage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AuthGate() {
  const { status, errorMessage, retry } = useAuth();
  const { pathname } = useLocation();
  const onLoginPage = Boolean(matchPath('/login', pathname));

  if (onLoginPage && status !== 'loading' && status !== 'local-login' && status !== 'signed-out' && status !== 'error') {
    const destination = status === 'admin' ? '/admin' : status === 'manager' ? '/manager' : '/';
    return <Navigate to={destination} replace />;
  }

  switch (status) {
    case 'loading':
      return <LoadingScreen />;

    case 'signed-out':
      if (!getInitData()) return onLoginPage ? <LocalLoginPage showHomeLink /> : <Navigate to="/login" replace />;
      return (
        <div className={styles.centerScreen}>
          <div className={styles.message} role="status">Hisobdan chiqdingiz.</div>
          <button type="button" className={styles.retryBtn} onClick={retry}>Telegram orqali kirish</button>
        </div>
      );

    case 'error':
      return (
        <div className={styles.centerScreen}>
          <div className={styles.wordmark}>YUK</div>
          <div className={styles.message}>{errorMessage ?? "Kirishda xato yuz berdi"}</div>
          <button className={styles.retryBtn} onClick={retry}>
            Qayta urinish
          </button>
        </div>
      );

    case 'local-login':
      return <LocalLoginPage showHomeLink={onLoginPage} />;

    case 'guest':
      return <RegisterPage />;

    case 'sender':
      return <SenderApp />;

    case 'driver':
      return <DriverGate />;

    case 'admin':
      return <AdminApp />;

    case 'manager':
      return <ManagerApp />;

    case 'unsupported':
      return (
        <div className={styles.centerScreen}>
          <div className={styles.wordmark}>YUK</div>
          <div className={styles.message}>Bu ilova sender/haydovchi uchun. Sizning rolingiz uchun mo'ljallanmagan.</div>
          <LogoutButton />
        </div>
      );
  }
}

export default function App() {
  const { pathname } = useLocation();
  // Ommaviy bosh sahifa Telegram tashqarisida, login sessiyasi yo'q tashrifchiga
  // ko'rsatiladi. Telegram Mini App va mavjud sessiyali brauzer odatdagi oqimda qoladi.
  if (pathname === '/' && !getInitData() && !getAccessToken()) {
    return <PublicLandingPage />;
  }

  return (
    <AuthProvider>
      <Suspense fallback={<LoadingScreen />}>
        <AuthGate />
      </Suspense>
    </AuthProvider>
  );
}
