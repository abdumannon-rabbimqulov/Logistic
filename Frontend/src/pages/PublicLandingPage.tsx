import { useEffect } from 'react';
import styles from './PublicLandingPage.module.css';

const DEFAULT_TELEGRAM_BOT_URL = 'https://t.me/Logistika_AIbot';
const telegramBotUrl = ((import.meta.env.VITE_TELEGRAM_BOT_URL as string | undefined) || DEFAULT_TELEGRAM_BOT_URL).trim();

function RouteIllustration() {
  return (
    <svg className={styles.routeArt} viewBox="0 0 640 480" role="img" aria-labelledby="route-title">
      <title id="route-title">Xaritadagi yuk yo‘nalishi</title>
      <defs>
        <pattern id="map-grid" width="46" height="46" patternUnits="userSpaceOnUse">
          <path d="M46 0H0V46" fill="none" stroke="currentColor" strokeOpacity=".08" />
        </pattern>
      </defs>
      <rect width="640" height="480" fill="url(#map-grid)" />
      <path d="M-30 356C108 291 141 411 275 337S473 225 668 290" fill="none" stroke="#fff" strokeOpacity=".08" strokeWidth="38" />
      <path d="M-30 356C108 291 141 411 275 337S473 225 668 290" fill="none" stroke="#fff" strokeOpacity=".16" strokeWidth="2" />
      <path d="M80 80 223 126 303 86 449 127 576 70M54 220 156 184 258 216 391 173 542 200M118 438 174 344 112 267 195 206" fill="none" stroke="#fff" strokeOpacity=".1" strokeWidth="2" />
      <path d="M158 338C220 306 235 225 302 230S386 300 443 241 474 169 523 141" fill="none" stroke="#ea5a15" strokeWidth="5" strokeLinecap="round" strokeDasharray="1 13" />
      <circle cx="158" cy="338" r="17" fill="#ea5a15" />
      <circle cx="158" cy="338" r="7" fill="#fff" />
      <circle cx="523" cy="141" r="17" fill="#ea5a15" />
      <circle cx="523" cy="141" r="7" fill="#fff" />
      <g transform="translate(327 201) rotate(18)">
        <rect x="-39" y="-26" width="78" height="52" rx="14" fill="#fff" />
        <path d="M-17-6h24v18h-24zM7-1h11l9 9v4H7z" fill="none" stroke="#0f1319" strokeWidth="3" strokeLinejoin="round" />
        <circle cx="-9" cy="16" r="5" fill="#ea5a15" />
        <circle cx="17" cy="16" r="5" fill="#ea5a15" />
      </g>
      <g className={styles.mapLabel}>
        <rect x="95" y="375" width="126" height="42" rx="21" fill="#252b33" />
        <text x="158" y="401" textAnchor="middle">Andijon</text>
        <rect x="460" y="82" width="126" height="42" rx="21" fill="#252b33" />
        <text x="523" y="108" textAnchor="middle">Manzil</text>
      </g>
    </svg>
  );
}

function TelegramAction({ secondary = false }: { secondary?: boolean }) {
  const className = secondary ? styles.secondaryAction : styles.primaryAction;
  const contents = <><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m21.6 4.4-3.3 15.2c-.2 1.1-.9 1.4-1.8.9l-5-3.7-2.4 2.3c-.3.3-.5.5-1 .5l.4-5.1 9.3-8.4c.4-.4-.1-.6-.6-.2L5.7 13.2.8 11.7c-1.1-.3-1.1-1.1.2-1.6L20.2 2.6c.9-.3 1.7.2 1.4 1.8Z" fill="currentColor" /></svg>Telegram botda boshlash<span aria-hidden="true">↗</span></>;
  if (!telegramBotUrl) {
    return <button className={className} type="button" disabled title="Telegram bot havolasi sozlanmagan">{contents}</button>;
  }
  return (
    <a
      className={className}
      href={telegramBotUrl}
      target="_blank"
      rel="noopener noreferrer"
    >
      {contents}
    </a>
  );
}

export function PublicLandingPage() {
  useEffect(() => {
    document.title = 'YUK — yuk tashishni oson boshlang';
  }, []);

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <a href="#top" className={styles.brand} aria-label="YUK bosh sahifasi">
          <span className={styles.brandMark} aria-hidden="true"><span /></span>
          <span>YUK</span>
        </a>
        <nav className={styles.nav} aria-label="Asosiy navigatsiya">
          <a href="#how-it-works">Qanday ishlaydi</a>
          <a href="#features">Imkoniyatlar</a>
        </nav>
        <TelegramAction secondary />
      </header>

      <section className={styles.hero} id="top">
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}><span /> O‘zbekiston bo‘ylab yuk tashish</div>
          <h1>Yuk yo‘lingiz<br /><em>aniq</em> bo‘lsin.</h1>
          <p className={styles.intro}>Manzilni xaritadan tanlang, mos transportni belgilang va buyurtmani Telegram ichida kuzating.</p>
          <div className={styles.heroActions}>
            <TelegramAction />
            <a className={styles.learnLink} href="#how-it-works">Qanday ishlashini ko‘ring <span aria-hidden="true">↓</span></a>
          </div>
          {!telegramBotUrl && <p className={styles.setupNote}>Telegram bot havolasi hali sozlanmagan.</p>}
          <div className={styles.heroFootnote}><span className={styles.liveDot} /> Telefoningizdagi Telegram orqali ishlaydi</div>
        </div>
        <div className={styles.visual} aria-label="Yuk yo‘nalishini ko‘rsatuvchi xarita tasviri">
          <div className={styles.visualTop}><span>YUK · YO‘NALISH</span><span className={styles.status}><i /> Reja tayyor</span></div>
          <RouteIllustration />
          <div className={styles.routeCard}>
            <div className={styles.routeIcon}><span /></div>
            <div><small>YUK MANZILI</small><strong>Yo‘nalishni o‘zingiz tanlang</strong></div>
            <span className={styles.routeArrow} aria-hidden="true">↗</span>
          </div>
          <span className={styles.coord} aria-hidden="true">40° 46′ 28″ N&nbsp;&nbsp; 72° 20′ 31″ E</span>
        </div>
      </section>

      <section className={styles.trustStrip} aria-label="Xizmatning asosiy yondashuvi">
        <span>Manzil — xaritadan</span><i />
        <span>Buyurtma — Telegramda</span><i />
        <span>Holat — doim ko‘z oldingizda</span>
      </section>

      <section className={styles.features} id="features">
        <div className={styles.sectionIntro}>
          <span className={styles.sectionKicker}>YUK BILAN ISHLASH</span>
          <h2>Har bir qadam<br />o‘z joyida.</h2>
          <p>Yuk yuborishni boshlashdan yetkazilishini kuzatishgacha — kerakli jarayonlar bitta ilovada.</p>
        </div>
        <div className={styles.featureList}>
          <article className={styles.feature}>
            <span className={styles.featureNo}>A</span>
            <div><h3>Manzilni xaritadan belgilang</h3><p>Yuk olinadigan va yetkaziladigan nuqtani xaritada tanlang. Tasdiqlashdan oldin manzilni ko‘rib chiqing.</p></div>
            <span className={styles.featureGlyph} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M25 13c0 7-9 15-9 15S7 20 7 13a9 9 0 1 1 18 0Z" /><circle cx="16" cy="13" r="3" /></svg></span>
          </article>
          <article className={styles.feature}>
            <span className={styles.featureNo}>B</span>
            <div><h3>Mos transportni tanlang</h3><p>Yukingizga mos transport turini belgilang va buyurtma narxi hamda yo‘nalish hisobini ko‘ring.</p></div>
            <span className={styles.featureGlyph} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M4 9h16v14H4zM20 14h5l4 4v5h-9z" /><circle cx="10" cy="24" r="3" /><circle cx="24" cy="24" r="3" /></svg></span>
          </article>
          <article className={styles.feature}>
            <span className={styles.featureNo}>C</span>
            <div><h3>Buyurtmani kuzatib boring</h3><p>Buyurtma holati va haydovchi haqidagi ma’lumotlarni ilovada bir joyda ko‘ring.</p></div>
            <span className={styles.featureGlyph} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M4 16s4-8 12-8 12 8 12 8-4 8-12 8S4 16 4 16Z" /><circle cx="16" cy="16" r="3" /></svg></span>
          </article>
        </div>
      </section>

      <section className={styles.process} id="how-it-works">
        <div className={styles.processHead}><span className={styles.sectionKicker}>BOSHLASH OSON</span><h2>Uch qadam.<br />Yuk yo‘lda.</h2></div>
        <div className={styles.steps}>
          <article><span>01</span><h3>Botni oching</h3><p>Telegram orqali YUK ilovasiga kiring.</p></article>
          <article><span>02</span><h3>Buyurtma tuzing</h3><p>Manzil, transport va yuk ma’lumotlarini kiriting.</p></article>
          <article><span>03</span><h3>Jarayonni kuzating</h3><p>Buyurtmangiz holatini ilovada tekshirib boring.</p></article>
        </div>
        <div className={styles.finalCta}><div><span className={styles.sectionKicker}>BOSHLASHGA TAYYORMISIZ?</span><h2>Yukni yo‘lga chiqaring.</h2></div><TelegramAction /></div>
      </section>

      <footer className={styles.footer}><a href="#top" className={styles.brand}><span className={styles.brandMark} aria-hidden="true"><span /></span><span>YUK</span></a><span>Yukingiz uchun aniq yo‘l.</span><a href="#top">Yuqoriga ↑</a></footer>
    </main>
  );
}
