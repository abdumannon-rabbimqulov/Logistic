"""Servislararo SHARTNOMA — yagona manba.

Core, support, notification va tracking servislari bir-birining kodini import
qilmaydi; ular faqat shu paketni bo'lishadi (har birining Docker image'iga
`contracts/` ko'chiriladi). Paketning o'zi hech narsaga bog'liq emas — faqat
standart kutubxona.

  * `events.py`      — exchange, event nomlari, navbatlar va konvert.
  * `redis_keys.py`  — jonli joylashuv kalitlari va kanallari.
  * `schemas/*.json` — har bir event payload'ining JSON Schema'si (Go servislari
                       ham shulardan foydalanadi).
  * `validate.py`    — sxema bo'yicha tekshiruv (testlarda).
  * `safe_logging.py` — loglarda token va bot sirlarini yashirish (har servis chaqiradi).
"""
