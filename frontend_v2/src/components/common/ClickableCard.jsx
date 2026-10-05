/**
 * A `div` that behaves like a button.
 *
 * Every gallery card in the dashboard is a clickable surface with children —
 * a favourite button, a selection checkbox, a metadata overlay. Writing that
 * shape means getting three things right every time, and each site got a
 * different subset wrong:
 *
 *   * `onClick` with no `tabIndex` is not reachable by keyboard. The card's
 *     whole purpose — open the lightbox — was mouse-only on four of the five
 *     card layouts.
 *   * `role="img"` is a *leaf* role (children presentational). Using it on the
 *     card root collapsed the entire subtree into one image node, which pruned
 *     the real `<button aria-pressed>` inside it out of the accessibility tree
 *     entirely. That was live on the grid card.
 *   * nothing fired on Enter or Space.
 *
 * One definition, so the next card cannot reintroduce any of them:
 *
 *   - <div className="..." onClick={onCardClick} role="img" aria-label={...}>
 *   + <ClickableCard className="..." onActivate={onCardClick} aria-label={...}>
 *
 * `onActivate` is the click handler; it is invoked for pointer clicks and for
 * Enter/Space, and nothing else. Nested interactive children are unaffected —
 * a keypress on a child button does not reach this element's handler, because
 * the event originates in the child.
 *
 * Pass `as` to render something other than a `div` (an `<a>` for a card that is
 * really a link); the keyboard and role contract travels with it.
 */
export function ClickableCard({
    as: Component = 'div',
    onActivate,
    className = '',
    ariaLabel,
    label,
    children,
    ...rest
}) {
    const handleKeyDown = (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        // Space would otherwise scroll the page, and Enter would submit an
        // ancestor form if there is one.
        event.preventDefault();
        event.stopPropagation();
        onActivate?.(event);
    };

    return (
        <Component
            className={className}
            role="button"
            tabIndex={0}
            onClick={onActivate}
            onKeyDown={handleKeyDown}
            {...(ariaLabel !== undefined ? { 'aria-label': ariaLabel } : {})}
            {...(label !== undefined ? { 'aria-label': label } : {})}
            {...rest}
        >
            {children}
        </Component>
    );
}

export default ClickableCard;