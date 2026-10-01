import { useCallback, useLayoutEffect, useState } from 'react';
import {
    useVirtualizer,
    observeElementOffset,
    observeWindowOffset,
} from '@tanstack/react-virtual';

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
 * Replaces `useWindowVirtualizer` at the gallery and the timeline.
 *
 * On `scrollMargin`: the previous version of this comment claimed it was
 * "deliberately not accepted", because with a real scroll element
 * `virtualItem.start` is already relative to that element's content box, and
 * subtracting a document-level margin double-counted it. The first half is right
 * and the conclusion was wrong. Those are two different things:
 *
 *   - `virtualItem.start` is container-relative, so it must NOT be adjusted.
 *   - `scrollMargin` tells the virtualizer where the container *begins* inside
 *     the scroll element, which it needs to turn a scroll offset into a visible
 *     range of indices. Without it, the range is computed against the wrong
 *     origin.
 *
 * The gallery list does not start at the top of its scroll element — on desktop
 * the chrome above it is ~630px, and below `lg` the scroller is `window` and the
 * list is preceded by the header, toolbar, date rail and filter panel. The
 * measured consequence below `lg` was that the virtualizer gave up and rendered
 * **every** row: 200 of them, 36,759px of list, against 10 rows and 14,146px on
 * desktop for the same data. That defeats the point of virtualizing a 16k-image
 * library, and it is the other half of the "infinite scroll is jumpy" report.
 *
 * So it is supplied, measured from the DOM, and deliberately never subtracted
 * from `start`.
 *
 * The options object is built fresh on every render on purpose. `count`,
 * `estimateSize` and `getItemKey` are all closures over live render state, and
 * `useVirtualizer` re-reads its options on every render and re-renders when
 * they change; memoizing it would freeze the list at its first shape.
 * `observeElementRect` is module-level precisely so that the identity which
 * *does* have to be stable — the one the library uses to decide whether to
 * unsubscribe and resubscribe — is.
 */
/**
 * `observeElementOffset` that is correct for a window scroll element.
 *
 * `useVirtualizer`'s default offset observer reads `el.scrollTop`. On `window`
 * that property does not exist, so the scroll offset is `undefined`, the
 * visible-range maths degenerates, and the virtualizer falls back to rendering
 * **every** row.
 *
 * That is not theoretical. Below `lg` the app shell does not make a pane the
 * scroller — `Layout.jsx` applies `lg:overflow-y-auto`, so on a phone the
 * document scrolls and `resolveScrollRoot` correctly returns `window`. Measured
 * on the session view at 390px: **200 rows in the DOM, 36,759px of list**,
 * against 10 rows and 14,146px on desktop for the same data. So on a phone the
 * gallery was not virtualizing at all, which is the other half of the
 * "infinite scroll is jumpy" report and a real cost on a 16k-image library.
 *
 * The matching rect observer was already supplied (see `observeElementRect`
 * above); this supplies its counterpart, so the pair is chosen from the same
 * element rather than one being right and the other not.
 */
function observeListOffset(instance, cb) {
    const el = instance.scrollElement;
    if (!el) return undefined;
    const targetWindow = instance.targetWindow;
    const isWindowScroll = el === targetWindow || el === targetWindow?.document;
    return isWindowScroll
        ? observeWindowOffset(instance, cb)
        : observeElementOffset(instance, cb);
}

export function useListVirtualizer(ref, options) {
    const getScrollElement = useScrollElement(ref, options.scrollRoot ?? null);
    const [scrollMargin, setScrollMargin] = useState(0);

    // Where the list begins inside whatever scrolls it. Re-measured when the
    // scroll element changes, on resize, and once more after layout settles —
    // the chrome above the gallery reflows when filters collapse, which moves
    // the list without resizing the window.
    useLayoutEffect(() => {
        const el = getScrollElement();
        const measure = () => {
            const node = ref.current;
            if (!node) return;
            // For an element scroller, the offset is the container's own
            // distance from the scroller's content top. For `window`, it is the
            // container's document offset.
            const next = el === window
                ? node.getBoundingClientRect().top + window.scrollY
                : node.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop;
            setScrollMargin((prev) => (Math.abs(prev - next) < 1 ? prev : Math.round(next)));
        };
        measure();
        const target = el === window ? window : el;
        target.addEventListener('resize', measure);
        // A collapsed filter panel or a rotated phone changes it without a resize.
        const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null;
        if (ro && ref.current) ro.observe(ref.current);
        return () => {
            target.removeEventListener('resize', measure);
            ro?.disconnect();
        };
    }, [getScrollElement, ref, options.scrollRoot]);

    return useVirtualizer({
        ...options,
        scrollMargin,
        getScrollElement,
        observeElementRect,
        observeElementOffset: observeListOffset,
    });
}
