"""Hodisa shartnomasi — asosiy ilovadagi `services/queue.py` bilan BIR XIL bo'lishi shart.

Bu xizmat asosiy kodni import qilmaydi (alohida image). Mosligini
`tests/test_event_contract.py` tekshiradi.
"""

EVENTS_EXCHANGE = "logistika.events"

EVENT_ORDER_STATUS_CHANGED = "order.status_changed"
EVENT_ORDER_WAYPOINT_CHANGED = "order.waypoint_changed"
EVENT_ORDER_TRIP_STARTED = "order.trip_started"
EVENT_SUPPORT_TICKET_CREATED = "support.ticket_created"
EVENT_SUPPORT_TICKET_REPLIED = "support.ticket_replied"
EVENT_SUPPORT_TICKET_STATUS_CHANGED = "support.ticket_status_changed"

SUPPORT_NOTIFICATIONS_QUEUE = "support.notifications"
SUPPORT_NOTIFICATIONS_PATTERN = "support.*"
ORDER_NOTIFICATIONS_QUEUE = "notifications.order_events"
ORDER_NOTIFICATIONS_PATTERN = "order.*"
