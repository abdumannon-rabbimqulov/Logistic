import { useState, type ReactNode } from 'react';
import { useAuth } from '../auth/AuthProvider';
import styles from './LogoutButton.module.css';

export function LogoutButton({ className = styles.button, icon }: { className?: string; icon?: ReactNode }) {
  const { logout } = useAuth();
  const [pending, setPending] = useState(false);

  async function handleClick() {
    setPending(true);
    try {
      await logout();
    } finally {
      setPending(false);
    }
  }

  return (
    <button type="button" className={className} onClick={handleClick} disabled={pending}>
      {icon}
      <span>{pending ? 'Chiqilmoqda…' : 'Chiqish'}</span>
    </button>
  );
}
