## 2024-05-30 - Focus states and disabled visuals on Selection Toolbar
**Learning:** Added `disabled:opacity-50 disabled:cursor-not-allowed` and explicit context-appropriate `focus-visible` styles to `SelectionToolbar.jsx` buttons. Without these styles, disabled buttons on interactive toolbars do not convey state cleanly and default browser focus rings may not adequately match the element’s styling context.
**Action:** Apply context-aware `focus-visible:ring-2 focus-visible:ring-offset-2` alongside disabled style utilities when creating new multi-action toolbars.
