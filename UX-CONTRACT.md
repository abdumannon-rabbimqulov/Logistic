# UX Contract

## Product context

- **Audience:** Senders, drivers, dispatch managers, and administrators using the YUK logistics product.
- **Primary jobs in this slice:** A sender starts a shipment, picks route points directly on the map, compares vehicle estimates, enters cargo details, places the request, and tracks its lifecycle.
- **Target market:** Uzbekistan; current product copy is Uzbek Latin.
- **Active locale:** Uzbek Latin (`uz-Latn`); no English fallback for owned UI.
- **Timezone/calendar:** `Asia/Tashkent`; send pickup instants to the API as ISO timestamps. Date display follows local device language only where the product does not provide a formatter.
- **Accessibility target:** WCAG 2.2 AA.

## Public landing entry

- An unauthenticated browser visit to `/` renders the Uzbek public landing page without starting authentication requests.
- Telegram Mini App visits to `/` continue through `AuthProvider` and open the authenticated product flow; a browser session with an existing access token also keeps its authenticated flow.
- The landing page Telegram CTA uses the build-time `VITE_TELEGRAM_BOT_URL`, defaulting to `https://t.me/Logistika_AIbot`.
- Public landing page metadata uses the YUK title and Uzbek description; the landing page scrolls normally and expands beyond the 480px Mini App canvas on desktop.

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Product purpose and sender design | `Frontend/README.md`; `design_handoff_yuk_asosiy_ekranlar/README.md` | Product / design handoff | 2026-11-20 |
| Order lifecycle and ownership | `order/models.py`, `order/schemas.py`, `order/router.py` | Domain/API | 2026-11-20 |
| Dispatch starts after creation | `order/service.py`, `services/dispatch.py` | Domain behavior | 2026-11-20 |
| Saved address storage | `Frontend/src/hooks/useSavedAddresses.ts` | Implementation evidence; local device storage | 2026-11-20 |
| Payment and legal copy | Not in this sender screen scope | — | — |

## Visual contract

- **Project design:** `DESIGN.md`.
- **Runtime token source:** `Frontend/src/styles/tokens.css`.
- **Mapping:** CSS Modules and shared components consume custom properties from the runtime token file; no duplicate theme adapter exists.
- **Drift gate:** compare DESIGN.md values to `tokens.css`, then inspect a sender home and order screen.
- **Supported themes:** light theme.
- **Design owner:** project UI maintainers; source handoff is the basis for the current sender visual language.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Route Point Selection | `MapPointPicker` | this contract + reverse-geocoding API | origin / destination | pan or tap map, preview address, explicit confirm, geocode fallback |
| Address Search | `AddressSearchSheet` inside `MapPointPicker` | this contract + geocoding API | optional map-centered search | debounce, clear, IME, stale response, error/retry; selecting a result recenters the draft only |
| Bottom Sheet Modal | `BottomSheetModal` | this contract | modal, mobile anchored | focus trap, Escape, inert app, restoration |
| Form | `CargoDetailsSheet` | order schema/API | create shipment | validation, preserved values, duplicate-submit guard |
| Select/Listbox | native controls where used; vehicle choice is a button group | current handoff + API options | native / pressed button group | keyboard and selected-state announcement |
| Date | `CargoDetailsSheet` date/time controls | API `pickup_at` | native picker | local timezone and keyboard review |
| Scrollbar | `Frontend/src/index.css` | DESIGN.md | stable gutter only by exception | computed root and scroll surface styles |
| Toast | route or shared inline feedback as implemented | this contract | inline for recoverable form errors | live region and duplicate feedback review |
| Create Order | `OrderPage` → `CargoDetailsSheet` → `createOrder` | order API and `order/service.py` | return to tracking | complete flow, API failure, duplicate prevention |

## Component behavior

| Component | Default | Hover | Focus | Active | Disabled | Busy | Error |
|---|---|---|---|---|---|---|---|
| Button | labeled, stable dimensions | subtle surface/darkening | visible 3px ring | brief press | no handler, not-allowed cursor | fixed-size label/spinner | inline for form failures |
| Icon button | localized accessible name | surface tint | visible ring | brief press | no handler | stable size | adjacent inline message when needed |
| Search | labeled input | — | input ring | n/a | — | reserved status line | distinct error with retry |
| Modal sheet | title and description by content | — | receives focus, traps Tab | n/a | — | body controls own busy state | stays open so user can recover |
| Vehicle choice | button, `aria-pressed` | surface tint | visible ring | pressed state | unavailable option disabled | n/a | estimates explain failure |

## Dataset navigation

- Sender orders use the API's server list; current home surfaces one active shipment and up to three recent terminal orders.
- Loading, empty, and request failure are distinct. A failed API call must never be represented as an empty dataset.
- Shipment list state and filters are not currently shareable or persisted in URL; home uses a fixed recent subset.
- Selecting a home shipment opens its tracking route; back returns through browser/router history.

## Flow ledger

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome | Source ref |
|---|---|---|---|---|---|---|---|
| Create shipment | home CTA, transport shortcut, saved address, or repeat action → final cargo submit | disable repeat submit; preserve cargo form values | `/orders/:id` tracking page | tracking page displays created lifecycle state | keep sheet open and entered values; show inline API error | focus remains in sheet after failure; tracking heading after success | `order/router.py`, `order/service.py` |
| Route point selection | tap the origin or destination row → map picker | reverse geocode after map settles; confirm disabled while resolving | explicit confirmation returns the chosen point to the composer | address, route, and estimate update | keep the picker open; coordinates remain selectable when reverse geocoding has no street label | restore the activated address row after close | `MapPointPicker`, `/orders/geocode/reverse` |
| Address search | open search from the map picker and type 3+ characters or retry | 300ms debounce, latest request wins | result recenters the map preview; it never commits the route point | user reviews the map and confirms the point | retry search; clear restores input focus; return to map selection | restore the search control or map picker context after close | `AddressSearchSheet`, `/orders/geocode/search` |
| Vehicle choice | activate a vehicle button | selected state updates immediately; estimate is server-owned | remain on composer | selected vehicle, price, distance, and time update | explain estimate error and offer retry | selected button retains focus | `/orders/estimate-price` |
| Cancel/back | activate back or dismiss sheet | no submit in progress | previous route/composer | none | no data change | restore trigger focus for modal close | React Router + `BottomSheetModal` |

## Navigation and responsive behavior

- Set a localized document title per route.
- Sender home uses document scrolling and fixed bottom navigation; reserve its height in content padding.
- Order composer is a bounded full-height map with a safe-area-aware bottom sheet.
- Modal bottom sheets use dialog semantics, inert background, focus trap, Escape dismissal, scroll lock, and trigger focus restoration.
- Preserve full route names in accessible text when visual layout truncates them.

## Overlays and feedback

- **Modal primitive:** shared `BottomSheetModal`.
- **Destructive actions:** confirm only when the operation is destructive or hard to reverse; do not add confirmation to routine address selection.
- **Toast placement:** no global toast owner is established for the sender slice; inline errors remain next to the affected workflow.
- **Unsaved changes:** preserve cargo details on API errors; ask before abandoning a non-empty cargo form if navigation guard is added.
- **Layer order:** app modal sheet above page navigation and floating map actions.

## Async and resilience

- Reads are pessimistic. Home sections load independently and preserve successful sections if another API read fails.
- Request results are committed only if they belong to the latest home/search request.
- Every route-point entry opens `MapPointPicker` first. The map stays the selection surface for pickup and delivery; the fixed center pin follows pan/tap interaction, and the selected point is committed only with “Shu manzilni tanlash”.
- Optional address search is debounced 300ms, composition-safe, clearable, and stale-response-safe. A chosen search result only recenters the picker; it does not silently replace an order point.
- Network retry for an uncertain order-create result is **unresolved**: `POST /orders` starts dispatch and no idempotency key or duplicate-detection contract was found. Do not automatically retry an ambiguous create response until the API/domain owner provides idempotency or a reconciliation rule.
- Session expiry follows the existing `AuthProvider` flow.

## Validation

- `CargoDetailsSheet` is the create form owner. It must use `noValidate`, visible labels, field-associated inline errors, preserve entered values, focus the first invalid field, and block duplicate submission.
- Prices and lifecycle state come from the server; the client must not infer a final order price from its own formula.
- Addresses and coordinates are personal data; do not put them in URLs, analytics, or global toasts.

## Verification

- Static project check: `python <frontend-design-premium>/scripts/audit_project.py . --mode strict`.
- Frontend checks: `npm run lint`, `npm run build`.
- Browser/device matrix: sender home and order composer at phone and desktop widths; loading, empty, read failure, search no-result/error/retry, keyboard and Escape, focus restoration, and reduced motion.
- Canonical sibling flow: sender tracking screen for status language, navigation, and route vocabulary.
- Known release risk: order-create ambiguity requires API idempotency/reconciliation policy; no safe client-only guarantee is asserted.
