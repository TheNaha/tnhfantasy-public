# Palette's Journal

This journal tracks critical UX and accessibility learnings for the application.

## 2024-05-22 - Icon-only Resolution Selectors
**Learning:** The resolution selector used a grid of icon-only buttons with visual representations of aspect ratios. While visually intuitive, they lacked text alternatives, making them inaccessible to screen reader users and ambiguous for some sighted users.
**Action:** Always include `aria-label` and `title` attributes on icon-only buttons to describe the action and the specific values (e.g., "Set aspect ratio 1:1, 1024x1024 pixels"). Also, use `aria-pressed` to indicate selection state on toggle/selection groups.

## 2024-05-23 - Accessible Dynamic Lists (Queue Visualization)
**Learning:** The job queue used `div` elements with `onClick` handlers for list items, making them inaccessible to keyboard users. Screen readers also couldn't identify the list structure or interact with the items.
**Action:** Convert interactive list items to `<button>` elements to ensure native keyboard focus and activation. Use `aria-label` to provide context (e.g., job status and prompt) that might be split across multiple visual elements. For collapsible sections, always pair the toggle button with `aria-expanded` and `aria-controls`.
