import { useEffect, useState } from 'react';
import { deleteAccount, getMe } from '../api/auth';
import { ApiError } from '../api/client';
import { useAuth } from '../auth/AuthProvider';
import { MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, usePasswordForm } from '../hooks/usePasswordForm';
import { BottomSheetModal } from './BottomSheetModal';
import styles from './AccountSettingsSection.module.css';

// Login/parol va akkauntni o'chirish. Ikkala ekranda ham (sender profili va
// haydovchi profili) bir xil bo'lgani uchun alohida komponentga chiqarilgan.
// Admin/menejer paneli uchun desktop varianti — admin/pages/AdminProfile.tsx.

function ChangePasswordSheet({
  hasPassword: initialHasPassword,
  onClose,
  onSaved,
}: {
  hasPassword: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  // Oyna ochilgandagi holat qotiriladi: saqlangach ota komponent `hasPassword=true`
  // qiladi, lekin bu oynadagi sarlavha/xabar "o'rnatildi" bo'lib qolishi kerak.
  const [hasPassword] = useState(initialHasPassword);
  const f = usePasswordForm(hasPassword, onSaved);
  const title = hasPassword ? "Parolni o'zgartirish" : "Parol o'rnatish";

  return (
    <BottomSheetModal title={title} onClose={onClose}>
      <div className={styles.form}>
        {f.done ? (
          <>
            <div className={styles.success}>
              {hasPassword ? "Parol muvaffaqiyatli o'zgartirildi" : "Parol o'rnatildi"}
            </div>
            <button className={styles.submit} onClick={onClose}>
              Yopish
            </button>
          </>
        ) : (
          <>
            {f.error && <div className={styles.error}>{f.error}</div>}

            {!hasPassword && (
              <div className={styles.hint}>
                Parol o'rnatsangiz, saytga brauzerdan ham telefon raqamingiz va shu parol
                bilan kira olasiz.
              </div>
            )}

            {hasPassword && (
              <label className={styles.field}>
                <span className={styles.label}>Joriy parol</span>
                <input
                  className={styles.input}
                  type="password"
                  value={f.oldPassword}
                  autoComplete="current-password"
                  onChange={(e) => f.setOldPassword(e.target.value)}
                />
              </label>
            )}

            <label className={styles.field}>
              <span className={styles.label}>Yangi parol</span>
              <input
                className={styles.input}
                type="password"
                value={f.newPassword}
                autoComplete="new-password"
                maxLength={MAX_PASSWORD_LENGTH}
                onChange={(e) => f.setNewPassword(e.target.value)}
              />
              {f.tooShort && (
                <span className={styles.invalid}>Kamida {MIN_PASSWORD_LENGTH} ta belgi bo'lishi kerak</span>
              )}
            </label>

            <label className={styles.field}>
              <span className={styles.label}>Yangi parolni takrorlang</span>
              <input
                className={styles.input}
                type="password"
                value={f.confirm}
                autoComplete="new-password"
                maxLength={MAX_PASSWORD_LENGTH}
                onChange={(e) => f.setConfirm(e.target.value)}
              />
              {f.mismatch && <span className={styles.invalid}>Parollar mos kelmadi</span>}
            </label>

            <button className={styles.submit} disabled={!f.valid || f.saving} onClick={f.save}>
              {f.saving ? 'Saqlanmoqda...' : hasPassword ? "O'zgartirish" : "O'rnatish"}
            </button>
          </>
        )}
      </div>
    </BottomSheetModal>
  );
}

function DeleteAccountSheet({ onClose }: { onClose: () => void }) {
  const { logout } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirmDelete() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteAccount();
      // Server akkauntni deaktivatsiya qildi — endi mavjud tokenlar bilan ishlash
      // ma'nosiz, shuning uchun to'liq chiqib, autentifikatsiya oqimini qaytadan
      // boshlaymiz (logout tokenlarni ham tozalaydi).
      await logout();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Akkauntni o'chirib bo'lmadi");
      setBusy(false);
    }
  }

  return (
    <BottomSheetModal title="Akkauntni o'chirish" onClose={onClose}>
      <div className={styles.form}>
        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.warning}>
          Akkaunt o'chirilgach tizimga kira olmaysiz. Buyurtmalar tarixi hisobot uchun
          saqlanib qoladi. Qaytadan foydalanmoqchi bo'lsangiz, yordam xizmatiga murojaat
          qilishingiz kerak bo'ladi.
        </div>

        <button className={styles.dangerBtn} disabled={busy} onClick={confirmDelete}>
          {busy ? "O'chirilmoqda..." : "Ha, akkauntni o'chirish"}
        </button>
        <button className={styles.ghostBtn} disabled={busy} onClick={onClose}>
          Bekor qilish
        </button>
      </div>
    </BottomSheetModal>
  );
}

export function AccountSettingsSection() {
  const [sheet, setSheet] = useState<'password' | 'delete' | null>(null);
  // Login (telefon) va parol holati — `null` = hali yuklanmagan.
  const [phone, setPhone] = useState<string | null>(null);
  const [hasPassword, setHasPassword] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (cancelled) return;
        setPhone(me.phone_number);
        setHasPassword(me.has_password);
      })
      .catch(() => {
        // Yuklanmasa — tugma baribir "o'zgartirish" rejimida ishlaydi (eski parol so'raladi).
        if (!cancelled) setHasPassword(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className={styles.section}>
      <div className={styles.sectionTitle}>Login va parol</div>

      <div className={styles.infoRow}>
        <span className={styles.infoLabel}>Login (telefon raqam)</span>
        <span className={styles.infoValue}>{phone || 'Kiritilmagan'}</span>
      </div>

      <button className={styles.rowBtn} disabled={hasPassword === null} onClick={() => setSheet('password')}>
        {hasPassword === false ? "Parol o'rnatish" : "Parolni o'zgartirish"}
      </button>

      <button className={styles.rowBtnDanger} onClick={() => setSheet('delete')}>
        Akkauntni o'chirish
      </button>

      {sheet === 'password' && hasPassword !== null && (
        <ChangePasswordSheet
          hasPassword={hasPassword}
          onClose={() => setSheet(null)}
          onSaved={() => setHasPassword(true)}
        />
      )}
      {sheet === 'delete' && <DeleteAccountSheet onClose={() => setSheet(null)} />}
    </div>
  );
}
