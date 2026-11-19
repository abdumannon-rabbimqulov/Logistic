"""Murojaat holati o'tish qoidalari — bitta joyda, router va testlar uchun.

    open ──► in_progress ──► resolved ──► closed
      │           ▲  │           │ ▲
      │           └──┼───────────┘ │   (xodim hal qilinganini qayta ochishi mumkin)
      └──────────────┴─────────────┴──► closed   (yakuniy, qayta ochilmaydi)

- CLOSED — yakuniy holat: hech kim qayta ocholmaydi (yangi murojaat ochiladi).
- Foydalanuvchi (murojaat egasi) faqat o'z murojaatini YOPA oladi.
- Xodim yuqoridagi strelkalar bo'yicha istalgan o'tishni qila oladi.
"""

from __future__ import annotations

from support_service.models import TicketStatus

S = TicketStatus

STAFF_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    S.OPEN: frozenset({S.IN_PROGRESS, S.RESOLVED, S.CLOSED}),
    S.IN_PROGRESS: frozenset({S.OPEN, S.RESOLVED, S.CLOSED}),
    S.RESOLVED: frozenset({S.IN_PROGRESS, S.CLOSED}),
    S.CLOSED: frozenset(),
}

OWNER_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    S.OPEN: frozenset({S.CLOSED}),
    S.IN_PROGRESS: frozenset({S.CLOSED}),
    S.RESOLVED: frozenset({S.CLOSED}),
    S.CLOSED: frozenset(),
}


def allowed_transitions(current: TicketStatus, *, is_staff: bool) -> frozenset[TicketStatus]:
    table = STAFF_TRANSITIONS if is_staff else OWNER_TRANSITIONS
    return table[current]


def can_transition(current: TicketStatus, new: TicketStatus, *, is_staff: bool) -> bool:
    return new in allowed_transitions(current, is_staff=is_staff)
