import { useCallback } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

/**
 * Virtualizing a list inside this app's layout.
 *
 * The app shell (`Layout.jsx`) puts the page body in
 * `flex-1 relative z-10 lg:overflow-y-auto` and gives it
 * `id="main-scroll-container"`. On any viewport at `lg` and above, the window
 * itself never scrolls: the pane does. That distinction has broken three
 * separate things, each of which looked fine in isolation:
 *
 *   - infinite scroll measured its sentinel against the viewport
 *   - the gallery virtualizer bound `useWindowVirtualizer` to `window`, so its
 *     `scrollOffset` stayed 0 forever and it rendered only the first viewportful
 *   - the scroll-margin helper added `window.scrollY` (always 0) to a
 *     viewport-relative `rect.top`
 *
 * All three are the same mistake, so they share one resolver.
 */

export function resolveScrollRoot(element, explicitRoot = null) {
    if (explicitRoot) return explicitRoot;
    let el = element?.parentElement ?? null;
    while (el && el !== document.body) {
        const overflowY = getComputedStyle(el).overflowY;
        if (overflowY === 'auto' || overflowY === 'scroll') return el;
        el = el.parentElement;
    }
    return null;
}

/**
 * The ancestor that actually scrolls, as opposed to one that merely declares it.
 *
 * `resolveScrollRoot` answers "which element has `overflow-y: auto`", which below
 * `lg` is `main` — and below `lg` `main` does not scroll. `Layout.jsx` gives it
 * `overflow-y-auto` unconditionally so the `lg` pane behaviour exists, but under
 * `lg` the element is content-height and the *window* is what moves. Measured at
 * 390px: `main.clientHeight === main.scrollHeight` at 3697, so it has no scroll
 * range at all, and it never will — appending children grows both numbers
 * together.
 *
 * That makes it a trap for anything that compares a sentinel's position to its
 * bounds. `bounds.bottom` moves down by exactly as much as the sentinel does, so
 * `rect.top < bounds.bottom + margin` is true forever, and a "the end is near, load
 * another page" check re-fires on every settle with no user input. Measured on the
 * gallery at 390px: **27 pages — 540 items — requested in 24 seconds with zero
 * interaction**, against 10 images in the DOM.
 *
 * ## Why "can it scroll right now?" is the wrong test
 *
 * The obvious predicate is `scrollHeight > clientHeight`, and it breaks desktop:
 * before enough pages have loaded, `main` has no overflow either, so the resolver
 * falls through to `window` — which never scrolls at `lg`, because the app shell is
 * `lg:h-screen lg:overflow-hidden`. Nothing loads, nothing grows, nothing scrolls:
 * infinite scroll deadlocks at the top of the page. Measured before this was
 * corrected: 12 deliberate scroll gestures on a 1280px viewport fetched 0 pages.
 *
 * The distinction is not about content, it is about *layout mode*, and it is
 * decided by height: a scroll pane is bounded by its parent, a content-sized box is
 * not. So the test is whether the element is taller than the viewport — if it is, it
 * is content-sized and the window is the scroller; if it is not, it is a pane.
 *
 *   390px:  main 3697 > innerHeight 844  -> content-sized -> window
 *   1280px: main  900 <= innerHeight 900 -> bounded pane  -> main
 *
 * Both are stable across load state, which is the property that matters: the answer
 * does not change as pages arrive, so it cannot oscillate.
 *
 * Not used by the virtualizers: `useScrollElement` wants the *declared* scroller,
 * because a virtualizer needs a stable element to measure against even in the
 * frame before it has any overflow. This is for the trigger decision only.
 */
export function resolveScrollableRoot(element, explicitRoot = null) {
    let el = explicitRoot || element?.parentElement || null;
    const first = Boolean(explicitRoot);
    while (el && (first || el !== document.body)) {
        const overflowY = getComputedStyle(el).overflowY;
        const declaresScroller = overflowY === 'auto' || overflowY === 'scroll';
        if (declaresScroller) {
            // Taller than the viewport means content-sized: it has no scroll range
            // and never will, because appending children grows it as well. The
            // window is what moves, so stop here and let the caller use it.
            return el.clientHeight <= window.innerHeight ? el : null;
        }
        el = el.parentElement;
    }
    return null;
}

/**
 * `getScrollElement` for `@tanstack/react-virtual`.
 *
 * An element that cannot be *measured* falls back to the viewport.
 * `@tanstack/react-virtual` derives its visible range from the scroll element's
 * height, so handing it a zero-height element makes `getVirtualItems()` return
 * an empty array and the list renders as nothing at all — which is what jsdom
 * (no layout engine) produces, and what a container that has not been laid out
 * yet produces for one frame. The viewport always has a height, so it is the
 * only answer that can show the rows.
 */
export function useScrollElement(ref, explicitRoot = null) {
    return useCallback(() => {
        const el = resolveScrollRoot(ref.current, explicitRoot);
        if (!el) return window;
        return el.clientHeight > 0 ? el : window;
    }, [ref, explicitRoot]);
}

/**
 * `observeElementRect` that is correct for a window scroll element.
 *
 * `useWindowVirtualizer` exists only to override this: the default
 * implementation reads `element.offsetHeight`, which is `undefined` on `window`,
 * so the visible range becomes `NaN` and nothing renders. `useVirtualizer` with
 * a `window` scroll element — which is what the fallback above produces on
 * narrow viewports and under jsdom — silently renders an empty list. Supplying
 * the override explicitly means one hook covers both cases, instead of forcing
 * every call site to branch on which hook to use.
 */
function observeElementRect(instance, cb) {
    const element = instance.scrollElement;
    if (!element) return undefined;
    const targetWindow = instance.targetWindow;
    if (!targetWindow) return undefined;

    const handler = (rect) => cb({ width: Math.round(rect.width), height: Math.round(rect.height) });

    const isWindowScroll = element === targetWindow || element === targetWindow.document;
    if (isWindowScroll) {
        handler({ width: targetWindow.innerWidth, height: targetWindow.innerHeight });
    } else {
        handler({ width: element.offsetWidth, height: element.offsetHeight });
    }

    if (!targetWindow.ResizeObserver) return () => {};
    const observer = new targetWindow.ResizeObserver((entries) => {
        const entry = entries[0];
        if (entry?.borderBoxSize?.[0]) {
            const box = entry.borderBoxSize[0];
            handler({ width: box.inlineSize, height: box.blockSize });
            return;
        }
        if (isWindowScroll) {
            handler({ width: targetWindow.innerWidth, height: targetWindow.innerHeight });
            return;
        }
        handler({ width: element.offsetWidth, height: element.offsetHeight });
    });
    observer.observe(isWindowScroll ? targetWindow.document.documentElement : element);

    return () => observer.disconnect();
}

/**
 * `useVirtualizer` bound to the element that actually scrolls this list.
 *
 * Replaces `useWindowVirtualizer` at the gallery and the timeline. The
 * `scrollMargin` option is deliberately not accepted: with a real scroll
 * element, `virtualItem.start` is already relative to that element's content
 * box, and subtracting a document-level margin double-counted it.
 *
 * The options object is built fresh on every render on purpose. `count`,
 * `estimateSize` and `getItemKey` are all closures over live render state, and
 * `useVirtualizer` re-reads its options on every render and re-renders when
 * they change; memoizing it would freeze the list at its first shape.
 * `observeElementRect` is module-level precisely so that the identity which
 * *does* have to be stable — the one the library uses to decide whether to
 * unsubscribe and resubscribe — is.
 */
export function useListVirtualizer(ref, options) {
    const getScrollElement = useScrollElement(ref, options.scrollRoot ?? null);
    return useVirtualizer({ ...options, getScrollElement, observeElementRect });
}
