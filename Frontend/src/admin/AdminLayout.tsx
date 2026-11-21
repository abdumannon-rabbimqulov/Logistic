import { NavLink, Outlet } from 'react-router-dom';
import { LogoutButton } from '../components/LogoutButton';
import {
  DashboardIcon,
  DriversIcon,
  LogoutIcon,
  OrdersIcon,
  ProfileIconAdmin,
  ServerIcon,
  SettingsIcon,
  TicketsIcon,
  TruckTypesIcon,
  UsersIcon,
} from './icons';
import styles from './AdminLayout.module.css';

const NAV = [
  { to: '/admin', label: 'Dashboard', Icon: DashboardIcon, end: true },
  { to: '/admin/orders', label: 'Buyurtmalar', Icon: OrdersIcon, end: false },
  { to: '/admin/drivers', label: 'Haydovchilar', Icon: DriversIcon, end: false },
  { to: '/admin/users', label: 'Foydalanuvchilar', Icon: UsersIcon, end: false },
  { to: '/admin/truck-types', label: 'Transport turlari', Icon: TruckTypesIcon, end: false },
  { to: '/admin/tickets', label: 'Yordam chatlari', Icon: TicketsIcon, end: false },
  { to: '/admin/monitoring', label: 'Server', Icon: ServerIcon, end: false },
  { to: '/admin/settings', label: 'Sozlamalar', Icon: SettingsIcon, end: false },
  { to: '/admin/profile', label: 'Profil', Icon: ProfileIconAdmin, end: false },
];

export function AdminLayout() {
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <span className={styles.brandMark}>YUK</span>
          <span className={styles.brandSub}>Admin</span>
        </div>

        <nav className={styles.nav}>
          {NAV.map(({ to, label, Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => (isActive ? styles.navItemActive : styles.navItem)}
            >
              <Icon />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <LogoutButton className={styles.logout} icon={<LogoutIcon />} />
      </aside>

      <main className={styles.content}>
        <Outlet />
      </main>
    </div>
  );
}
