import { useEffect, useState } from 'react';
import { getMe, updateMe } from '../../api/auth';
import { ApiError } from '../../api/client';
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, usePasswordForm } from '../../hooks/usePasswordForm';
import type { UserProfile } from '../../types/api';
import { PHONE_PLACEHOLDER } from '../../utils/phone';
import shared from '../shared.module.css';
import styles from './AdminProfile.module.css';

// Admin va menejer panelidagi "Profil": ism, login (telefon raqam) va parol.
// Mobil (sender/haydovchi) varianti — components/AccountSettingsSection.tsx.

function AccountCard({ profile, onSaved }: { profile: UserProfile; onSaved: (p: UserProfile) => void }) {
  const [fullName, setFullName] = useState(profile.full_name);
  const [phone, setPhone] = useState(profile.phone_number ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const changed = fullName.trim() !== profile.full_name || phone.trim() !== (profile.phone_number ?? '');
  const valid = fullName.trim().length > 0;

  async function save() {
    if (!changed || !valid || saving) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMe({
        full_name: fullName.trim(),
        // Bo'sh qoldirilsa telefon o'zgartirilmaydi (loginni o'chirib bo'lmaydi).
        ...(phone.trim() ? { phone_number: phone.trim() } : {}),
      });
      setFullName(updated.full_name);
      setPhone(updated.phone_number ?? '');
      setSaved(true);
      onSaved(updated);
    } catch (err) {
      // 409 — bu raqam boshqa foydalanuvchida; 422 — raqam formati noto'g'ri.
      setError(err instanceof ApiError ? err.message : "Saqlab bo'lmadi");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>Profil va login</h2>
        <p className={styles.cardSub}>
          Brauzerdan kirishda login sifatida telefon raqamingiz ishlatiladi.
        </p>
      </div>

      {error && <div className={shared.errorBanner}>{error}</div>}

      <div className={styles.fields}>
        <label className={styles.field}>
          <span className={styles.label}>Ism familiya</span>
          <input
            className={styles.input}
            value={fullName}
            maxLength={128}
            onChange={(e) => { setFullName(e.target.value); setSaved(false); }}
          />
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Login (telefon raqam)</span>
          <input
            className={styles.input}
            value={phone}
            inputMode="tel"
            autoComplete="username"
            placeholder={PHONE_PLACEHOLDER}
            onChange={(e) => { setPhone(e.target.value); setSaved(false); }}
          />
        </label>
      </div>

      <div className={styles.actions}>
        <button className={shared.primaryBtn} disabled={!changed || !valid || saving} onClick={save}>
          {saving ? 'Saqlanmoqda...' : 'Saqlash'}
        </button>
        {saved && <span className={styles.saved}>Saqlandi ✓</span>}
      </div>
    </div>
  );
}

function PasswordCard({
  hasPassword,
  notice,
  onSaved,
}: {
  hasPassword: boolean;
  /** Karta qayta yaratilganda ham ko'rinadigan xabar (parol birinchi marta o'rnatilgach). */
  notice?: string | null;
  onSaved: () => void;
}) {
  const f = usePasswordForm(hasPassword, onSaved);

  return (
    <div className={styles.card}>
      <div className={styles.cardHead}>
        <h2 className={styles.cardTitle}>{hasPassword ? "Parolni o'zgartirish" : "Parol o'rnatish"}</h2>
        <p className={styles.cardSub}>
          {hasPassword
            ? `Xavfsizlik uchun avval joriy parolni kiriting. Yangi parol kamida ${MIN_PASSWORD_LENGTH} ta belgi.`
            : `Sizda hali parol yo'q — hozir faqat Telegram orqali kira olasiz. Parol o'rnatsangiz, panelga brauzerdan telefon raqam va parol bilan ham kirasiz. Kamida ${MIN_PASSWORD_LENGTH} ta belgi.`}
        </p>
      </div>

      {f.error && <div className={shared.errorBanner}>{f.error}</div>}

      {/* Brauzer parol menejeri to'g'ri ishlashi uchun forma (Enter bilan ham yuboriladi). */}
      <form
        className={styles.fields}
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void f.save();
        }}
      >
        {hasPassword && (
          <label className={styles.field}>
            <span className={styles.label}>Joriy parol</span>
            <input
              className={styles.input}
              type="password"
              autoComplete="current-password"
              value={f.oldPassword}
              onChange={(e) => f.setOldPassword(e.target.value)}
            />
          </label>
        )}

        <label className={styles.field}>
          <span className={styles.label}>Yangi parol</span>
          <input
            className={styles.input}
            type="password"
            autoComplete="new-password"
            maxLength={MAX_PASSWORD_LENGTH}
            value={f.newPassword}
            onChange={(e) => f.setNewPassword(e.target.value)}
          />
          {f.tooShort && <span className={styles.invalid}>Kamida {MIN_PASSWORD_LENGTH} ta belgi</span>}
        </label>

        <label className={styles.field}>
          <span className={styles.label}>Yangi parolni takrorlang</span>
          <input
            className={styles.input}
            type="password"
            autoComplete="new-password"
            maxLength={MAX_PASSWORD_LENGTH}
            value={f.confirm}
            onChange={(e) => f.setConfirm(e.target.value)}
          />
          {f.mismatch && <span className={styles.invalid}>Parollar mos kelmadi</span>}
        </label>

        <div className={styles.actions}>
          <button type="submit" className={shared.primaryBtn} disabled={!f.valid || f.saving}>
            {f.saving ? 'Saqlanmoqda...' : hasPassword ? "O'zgartirish" : "O'rnatish"}
          </button>
          {(f.done || notice) && <span className={styles.saved}>{f.done ? 'Parol saqlandi ✓' : notice}</span>}
        </div>
      </form>
    </div>
  );
}

export function AdminProfile() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [passwordNotice, setPasswordNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((p) => {
        if (!cancelled) setProfile(p);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Profilni yuklab bo'lmadi");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className={shared.page}>
      <div className={shared.pageHead}>
        <div>
          <h1 className={shared.pageTitle}>Profil</h1>
          <div className={shared.pageSub}>Login, parol va shaxsiy ma'lumotlar</div>
        </div>
      </div>

      {error && <div className={shared.errorBanner}>{error}</div>}

      {!profile && !error && <div className={styles.skeleton} />}

      {profile && (
        <div className={styles.stack}>
          <AccountCard profile={profile} onSaved={setProfile} />
          <PasswordCard
            // Parol birinchi marta o'rnatilgach karta "o'zgartirish" rejimiga o'tadi —
            // `key` formani toza holatda qayta yaratadi.
            key={profile.has_password ? 'change' : 'set'}
            hasPassword={profile.has_password}
            notice={passwordNotice}
            onSaved={() => {
              if (!profile.has_password) setPasswordNotice("Parol o'rnatildi ✓");
              setProfile((p) => (p ? { ...p, has_password: true } : p));
            }}
          />
        </div>
      )}
    </div>
  );
}
