## 2025-02-14 - Semantic Accordions vs Divs
**Learning:** Custom accordion implementations using `div`s and `button`s often miss critical ARIA attributes (`aria-expanded`, `aria-controls`, `aria-labelledby`, `role="region"`), making them invisible or confusing to screen reader users. Nesting headers inside buttons (or vice versa incorrectly) also breaks semantic structure.
**Action:** Always use a reusable `CollapsibleSection` component that encapsulates the WAI-ARIA Accordion pattern, ensuring semantic HTML (`h3 > button`) and proper state management.
