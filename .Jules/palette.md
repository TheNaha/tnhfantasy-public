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

## 2024-05-18 - ImageLightbox Accessibility
**Learning:** Found that custom carousel implementations and modals (like `ImageLightbox`) often rely heavily on icon-only buttons (`lucide-react` icons like `X`, `ChevronLeft`, `ChevronRight`) without appropriate `aria-label`s, rendering them completely invisible or confusing to screen reader users. Additionally, custom indicator dots for carousels are frequently built as plain `button`s without `aria-label` or `aria-pressed` states to indicate the current active index.
**Action:** When creating or reviewing custom modals and image carousels, always ensure that:
1. Icon-only buttons have descriptive `aria-label` attributes.
2. The icons themselves are hidden from screen readers using `aria-hidden="true"`.
3. Custom indicators (like carousel dots) use `aria-label` to describe their target (e.g., "Go to image 1") and use `aria-pressed="true"` for the currently active state.
4. All interactive elements have clear focus indicators for keyboard navigation (e.g., `focus-visible:ring-2 focus-visible:ring-blue-500 outline-none`).

## 2024-05-26 - Interactive Divs and Toggle Buttons Accessibility
**Learning:** Some custom components, like `JobCard`, rely on `div` wrappers with `onClick` handlers but lack native keyboard navigation (`tabIndex`, `onKeyDown`) and semantic roles (`role="button"`). Similarly, action buttons functioning as toggles (e.g., Favorite button in `SelectionToolbar`) frequently omit `aria-pressed` states.
**Action:** Always assign `role="button"`, `tabIndex={0}`, and `onKeyDown` handlers to `div` elements intended to act as interactive components to support keyboard accessibility. Include proper `aria-label` and `aria-pressed` properties to convey state correctly to screen readers. Include proper focus indicators (like `focus-visible:ring-2 outline-none`) to show the user when the component has focus.

## 2025-03-16 - Hidden Text in Responsive Buttons
**Learning:** Responsive designs often hide text labels on smaller screens to save space (e.g., `<span className="hidden sm:inline">Filters</span>`). This practice inadvertently removes the accessible name for screen reader users on mobile devices if the button only contains an icon visually and the text is hidden using CSS like `display: none` (which `hidden` in Tailwind applies).
**Action:** Whenever text inside a button is conditionally hidden using CSS media queries, explicitly provide an `aria-label` to the `<button>` element to guarantee a persistent accessible name across all device sizes.

## 2026-03-18 - Missing ARIA Labels on Modals and Icon Buttons
**Learning:** Custom UI panels and modals (such as the CollectionsPanel, SelectCollectionModal, and CreateCollectionModal) often utilize icon-only buttons for critical actions (e.g., "Rename", "Delete", "Close"). Using only `title` attributes on these buttons is insufficient for comprehensive screen reader support. Moreover, selection grids (like color pickers or collection lists) built with `<button>` elements require explicit `aria-label` and `aria-pressed` states to communicate their purpose and active status accurately.
**Action:** When creating or updating custom modals, panels, and selection grids:
1. Ensure all icon-only buttons (including modal close buttons and action toggles) have descriptive `aria-label` attributes.
2. Hide purely decorative icons from screen readers using `aria-hidden="true"`.
3. For selection grids, use `aria-label` to describe the option and `aria-pressed` to indicate selection state, instead of relying purely on visual cues like styling differences.
