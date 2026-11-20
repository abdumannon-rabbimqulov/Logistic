---
version: alpha
name: YUK
description: "O'zbekiston bo'ylab yuk yuborish va tashishni boshqarish uchun mobil-first logistika mahsuloti."
colors:
  primary: "#EA5A15"
  accent-pressed: "#B63D0A"
  accent-tint: "#FDEDE2"
  action: "#C7470D"
  action-pressed: "#A83A08"
  background: "#FFFFFF"
  background-muted: "#F4F5F7"
  text: "#0F1319"
  text-muted: "#8A93A2"
  border: "#EAECF0"
  danger: "#D92D20"
  success: "#12875A"
typography:
  display:
    fontFamily: "'Space Grotesk', Inter, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "20px"
    lineHeight: "1.25"
  body:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "14px"
    lineHeight: "1.4"
  utility:
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, sans-serif"
    fontSize: "12px"
    lineHeight: "1.4"
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  pill: "999px"
spacing:
  mobile-gutter: "20px"
  section-gap: "22px"
  bottom-navigation: "78px"
  app-max-width: "480px"
components:
  primary-action:
    backgroundColor: "#C7470D"
    textColor: "#FFFFFF"
    height: "52px"
    rounded: "999px"
  card:
    backgroundColor: "#FFFFFF"
    textColor: "#0F1319"
    rounded: "16px"
  bottom-navigation:
    height: "78px"
    backgroundColor: "#FFFFFF"
  selected-control:
    backgroundColor: "#FDEDE2"
    textColor: "#B63D0A"
    rounded: "12px"
  brand-icon:
    textColor: "#EA5A15"
  muted-label:
    textColor: "#8A93A2"
  app-shell:
    backgroundColor: "#F4F5F7"
  danger-feedback:
    textColor: "#D92D20"
  success-feedback:
    textColor: "#12875A"
---

# YUK Design System

## Overview

### Creative North Star

YUK should feel like the clear instrument panel in a working delivery vehicle: route and cargo decisions stay legible at a glance, while one warm signal color marks the next useful action. The identity comes from the map, ordered route points, and transport silhouettes rather than decorative logistics imagery.

### Product context and register

- **Audience and primary job:** People and businesses in Uzbekistan arranging freight pickup and delivery; choose addresses and a vehicle, place a shipment request, and follow its status.
- **Target market(s) and evidence:** Uzbekistan; the project UI and service copy are Uzbek, address geocoding is integrated with Yandex, and the user identified this repository as their logistics project.
- **Locale(s) and language policy:** Uzbek Latin is the current interface language. Keep labels, validation, statuses, and accessibility names in Uzbek; do not mix in English fallback UI. Format local scheduling in `Asia/Tashkent`.
- **Usage scene:** Telegram Mini App on a phone, often used briefly while coordinating a pickup. Primary sender actions must fit touch use and remain readable in a bottom-sheet/map layout.
- **Register:** Product UI across sender, driver, manager, and admin routes; task clarity and status legibility lead.
- **Memorable signature:** The map-and-route-point order composer with a single burnt-orange action signal.
- **Restraint:** Dense operational data uses quiet surfaces, strong labels, and thin borders. Use shadows only for floating sheets and the home create-order card.
- **Anti-references:** Generic finance dashboards, decorative gradients, emoji truck iconography, and color-only status meaning.
- **Token ownership/runtime mapping:** `Frontend/src/styles/tokens.css` is the runtime source of truth. This file documents its design values; component styles consume the CSS custom properties. Drift review compares these frontmatter values with the tokens file and the source handoff in `design_handoff_yuk_asosiy_ekranlar/README.md`.

## Colors

The visual accent `#EA5A15` follows the approved sender-screen handoff and is reserved for selection, route marks, and small highlights. White text on that orange misses normal-text contrast, so filled actions use the darker action color `#C7470D` and pressed state `#A83A08`. Text on the orange tint uses `#B63D0A` to meet normal-text contrast. Use `#FDEDE2` for selected surfaces. `#0F1319` is the main text and active-order surface; `#F4F5F7` is a secondary surface; `#EAECF0` defines quiet boundaries; the border role is implemented by `--color-border` in `Frontend/src/styles/tokens.css`. Danger and success keep independent semantic roles and must not be replaced by brand orange.

## Typography

Use Space Grotesk for wordmarks, short headings, and key numeric values. Use Inter for Uzbek Latin body copy, controls, and utility labels. Keep critical data in sentence case with a 14px body baseline; small metadata may use 12px but must not carry the only explanation of an action. Allow flexible wrapping for long Uzbek labels and addresses instead of clipping important values.

## Layout

The sender and driver products are narrow, phone-first surfaces capped at 480px in the web preview and full width inside Telegram. Keep 20px horizontal gutters, safe-area-aware bottom actions, and the 78px fixed bottom navigation. The home page scrolls naturally. The order composer owns a full-height map with its own bounded bottom sheet; do not apply that fixed-height rule to ordinary content routes.

## Elevation & Depth

Prefer flat white cards with a 1px neutral border. Use a restrained `0 2px 10px rgba(15, 19, 25, .06)` shadow only on the home create-order card and floating sheets; use a stronger shadow below the map sheet to separate it from map content. Avoid ambient shadows on data lists.

## Shapes

Use 8/12/16/20px radii for utility controls through prominent cards, and pill corners for primary actions and compact chips. Inline icons are custom stroke SVGs, generally 1.6–1.9px. Do not use emoji as transport or navigation icons.

## Components

### Foundational visual states

Controls show hover, pressed, focus-visible, disabled, and busy states without changing their dimensions. Use an application-wide visible scrollbar theme; preserve operating-system high-contrast colors. Loading, empty, no-results, and error messages keep a reserved, consistent content area.

### Buttons and actions

Use solid dark orange for the primary action, outline or quiet surfaces for secondary actions, and red only for destructive intent. Important touch targets should approach 44px. While busy, keep the button size fixed and announce its state.

### Navigation and data display

Sender navigation is fixed to the bottom with four equal destinations. Mark the active destination with both icon and label color. Shipment rows preserve route, lifecycle status, and price; long routes may truncate visually but must remain available to assistive technology.

### Forms and overlays

Use native labeled fields where their interaction is acceptable. Address search is debounced, clearable, composition-safe, and stale-response-safe. Bottom sheets are modal: they receive focus, trap Tab navigation, close on Escape, make the app root inert, lock background scrolling, and restore focus when dismissed.

### Iconography

Use the maintained inline SVG icon set under `Frontend/src/components/icons.tsx`; use a consistent stroke family and keep visible text for uncommon actions.

### Motion

Use short state feedback, not ambient motion. Keep reduced-motion users on the same information and feedback path. Any GPS pulse must not be the sole signal that location is active.

### Content and data visualization

Write direct Uzbek Latin labels with a verb that matches the outcome. Use `so'm` formatting supplied by the API formatter. A request in progress, a retryable failure, and a genuinely empty list are distinct states.

## Do's and Don'ts

- **Do:** Keep route, vehicle, cargo, and order lifecycle information readable with one hand on a phone.
- **Do:** Use orange for brand emphasis and a darker action token for white-on-color labels.
- **Don't:** Show a failed request as an empty order history or empty vehicle catalog.
- **Don't:** Hide scrollbars or make a map pin pulse the only location cue.
