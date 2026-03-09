# Palette's Journal

This journal tracks critical UX and accessibility learnings for the application.

## 2024-05-22 - Icon-only Resolution Selectors
**Learning:** The resolution selector used a grid of icon-only buttons with visual representations of aspect ratios. While visually intuitive, they lacked text alternatives, making them inaccessible to screen reader users and ambiguous for some sighted users.
**Action:** Always include `aria-label` and `title` attributes on icon-only buttons to describe the action and the specific values (e.g., "Set aspect ratio 1:1, 1024x1024 pixels"). Also, use `aria-pressed` to indicate selection state on toggle/selection groups.

## 2024-05-23 - Accessible Dynamic Lists (Queue Visualization)
**Learning:** The job queue used `div` elements with `onClick` handlers for list items, making them inaccessible to keyboard users. Screen readers also couldn't identify the list structure or interact with the items.
**Action:** Convert interactive list items to `<button>` elements to ensure native keyboard focus and activation. Use `aria-label` to provide context (e.g., job status and prompt) that might be split across multiple visual elements. For collapsible sections, always pair the toggle button with `aria-expanded` and `aria-controls`.

## 2026-02-26 - Modal Accessibility (Model Selector)
**Learning:** The Model Selector modal lacked standard closing behaviors (Escape key, backdrop click), forcing users to hunt for the small "X" button. This is a common barrier for keyboard users and an annoyance for mouse users.
**Action:** For all custom modals, implement `useEffect` for the Escape key and an `onClick` handler on the backdrop that calls the close function. Ensure the modal content prevents propagation of clicks to avoid accidental closing.
## 2024-05-18 - Avoid whole-file formatting when strict line-change limits are enforced
**Learning:** Running `npx prettier --write <path>` on an entire file when a strict <50 lines change limit is enforced will likely violate the limit due to unrelated stylistic changes, polluting the PR and making review difficult.
**Action:** When working under strict line limits, only format the specific lines modified, or ignore automated whole-file formatting and format manually.

## 2024-05-24 - Range Sliders Accessibility
**Learning:** Range sliders that mirror number inputs often miss accessible names because their corresponding labels are only associated via `htmlFor` with the number input. This makes them inaccessible or ambiguous for screen readers.
**Action:** When a UI provides parallel inputs (e.g., number and range slider) for a single value, explicitly provide `aria-label` or `aria-labelledby` to the secondary input, even when there's an associated `<label>` meant for the primary input.

## 2024-05-25 - Accessible Form Labels in Filter Panels
**Learning:** Filter panels often use visual labels (like `<label>Model</label> <input />`) without programmatic association, making them inaccessible to screen readers.
**Action:** Always use `useId()` to generate unique IDs and explicitly associate `<label htmlFor={id}>` with `<input id={id}>` or `<select id={id}>`, and use `aria-expanded` and `aria-controls` for the filter toggle button.
