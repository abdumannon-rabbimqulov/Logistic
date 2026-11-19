import { useState } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { getMyDriverCabinetOrNull } from '../api/drivers';
import { useChatDeepLink } from '../components/chat/useChatDeepLink';
import type { DriverCabinet } from '../types/api';
import { CabinetContext } from './DriverCabinetContext';
import { DriverActiveOrderPage } from './DriverActiveOrderPage';
import { DriverEarningsPage } from './DriverEarningsPage';
import { DriverHomePage } from './DriverHomePage';
import { DriverOrdersPage } from './DriverOrdersPage';
import { DriverProfilePage } from './DriverProfilePage';
import { LiveMapPage } from './LiveMapPage';
import { OrderChatPage } from './OrderChatPage';
import { SupportChatPage } from './SupportChatPage';

interface Props {
  initialCabinet: DriverCabinet;
}

export function DriverApp({ initialCabinet }: Props) {
  const [cabinet, setCabinet] = useState<DriverCabinet>(initialCabinet);
  // Telegram'dagi "Chatni ochish" (`startapp=chat_<id>`) — chat sahifasiga o'tish.
  useChatDeepLink();

  async function reloadCabinet() {
    const fresh = await getMyDriverCabinetOrNull();
    if (fresh) setCabinet(fresh);
  }

  return (
    <CabinetContext.Provider value={{ cabinet, setCabinet, reloadCabinet }}>
      <Routes>
        <Route path="/" element={<DriverHomePage />} />
        <Route path="/active/:orderId" element={<DriverActiveOrderPage />} />
        {/* Buyurtma chati — sender bilan bir xil yo'l (bildirishnoma havolasi ikkalasida ishlaydi). */}
        <Route path="/orders/:orderId/chat" element={<OrderChatPage />} />
        <Route path="/orders" element={<DriverOrdersPage />} />
        <Route path="/earnings" element={<DriverEarningsPage />} />
        <Route path="/map" element={<LiveMapPage role="driver" />} />
        {/* Yordam chati haydovchi uchun ham ochiq — support har qanday autentifikatsiyalangan
            foydalanuvchini qabul qiladi (get_principal), rol farqi yo'q. */}
        <Route path="/messages" element={<SupportChatPage />} />
        <Route path="/messages/:ticketId" element={<Navigate to="/messages" replace />} />
        <Route path="/profile" element={<DriverProfilePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </CabinetContext.Provider>
  );
}
