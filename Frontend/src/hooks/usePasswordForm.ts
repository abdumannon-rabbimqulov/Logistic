import { useState } from 'react';
import { changePassword } from '../api/auth';
import { ApiError } from '../api/client';

// Backend cheklovi (users/schemas.py ChangePasswordRequest).
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_LENGTH = 128;

/** Parol o'rnatish / o'zgartirish formasi holati. Mobil profil (bottom sheet) va
 *  admin/menejer paneli (desktop karta) ko'rinishi har xil, mantiq esa bitta —
 *  shuning uchun shu hook'da turadi.
 *
 *  `hasPassword=false` — foydalanuvchi Telegram orqali kirgan, paroli yo'q:
 *  "joriy parol" maydoni kerak emas, parol birinchi marta o'rnatiladi. */
export function usePasswordForm(hasPassword: boolean, onSuccess?: () => void) {
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const tooShort = newPassword.length > 0 && newPassword.length < MIN_PASSWORD_LENGTH;
  const tooLong = newPassword.length > MAX_PASSWORD_LENGTH;
  const mismatch = confirm.length > 0 && newPassword !== confirm;
  const valid =
    (!hasPassword || oldPassword.length > 0) &&
    newPassword.length >= MIN_PASSWORD_LENGTH &&
    !tooLong &&
    confirm.length > 0 &&
    !mismatch;

  async function save() {
    if (!valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      await changePassword(hasPassword ? oldPassword : null, newPassword);
      setDone(true);
      setOldPassword('');
      setNewPassword('');
      setConfirm('');
      onSuccess?.();
    } catch (err) {
      // Eski parol noto'g'ri bo'lsa backend 400 va aniq sabab qaytaradi.
      setError(err instanceof ApiError ? err.message : "Parolni saqlab bo'lmadi");
    } finally {
      setSaving(false);
    }
  }

  function touch() {
    setDone(false);
    setError(null);
  }

  return {
    oldPassword,
    setOldPassword: (v: string) => { touch(); setOldPassword(v); },
    newPassword,
    setNewPassword: (v: string) => { touch(); setNewPassword(v); },
    confirm,
    setConfirm: (v: string) => { touch(); setConfirm(v); },
    tooShort,
    tooLong,
    mismatch,
    valid,
    saving,
    error,
    done,
    save,
  };
}
