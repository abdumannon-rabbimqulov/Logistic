"""Chat holati o'tish qoidalari — bitta joyda, router va testlar uchun.

Har foydalanuvchiga bitta chat (`models.SupportTicket`). Holat — xodimlarning
ish navbati uchun, chat hech qachon yopilmaydi:

    open ◄──► in_progress ◄──► resolved ──► (foydalanuvchi yozsa) ──► open

- Holatni faqat xodim o'zgartiradi (uchala holat orasida erkin).
- Foydalanuvchi holatni o'zgartirmaydi: "hal qilingan" chatga yozsa, chat
  avtomatik qayta ochiladi (`crud.add_message`).
- CLOSED — eski qiymat (migratsiya 0003 gacha). Unga o'tib bo'lmaydi; shu
  holatda qolgan yozuvni xodim istalgan holatga o'tkaza oladi.
"""

from __future__ import annotations

from support_service.models import TicketStatus

S = TicketStatus

_ACTIVE = (S.OPEN, S.IN_PROGRESS, S.RESOLVED)

STAFF_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    status: frozenset(s for s in _ACTIVE if s != status) for status in S
}


def allowed_transitions(current: TicketStatus, *, is_staff: bool) -> frozenset[TicketStatus]:
    return STAFF_TRANSITIONS[current] if is_staff else frozenset()


def can_transition(current: TicketStatus, new: TicketStatus, *, is_staff: bool) -> bool:
    return new in allowed_transitions(current, is_staff=is_staff)
