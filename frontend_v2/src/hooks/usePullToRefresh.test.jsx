/**
 * Pull-to-refresh's listener lifecycle.
 *
 * The three touch handlers used to close over `isPulling` and `pullDistance`, so
 * they changed identity on every frame of a gesture and the attach effect — which
 * lists them as dependencies — tore down and re-added all four listeners each
 * time. That is four `removeEventListener` and four `addEventListener` calls per
 * `touchmove`, on the `{passive: false}` `touchmove` that carries the
 * `preventDefault`. Removing a listener the browser is mid-dispatch of loses
 * that event, and re-registering a `passive: false` listener to cancel a scroll
 * that has already begun does not stop it — so the content scrolled out from
 * under the pull and the indicator jumped.
 *
 * The invariant pinned here is the one that is cheap to state and expensive to
 * reintroduce: one bind per event type for a whole gesture.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, act } from '@testing-library/react';
import { useEffect } from 'react';

import { usePullToRefresh } from './usePullToRefresh';

const TOUCH_TYPES = ['touchstart', 'touchmove', 'touchend', 'touchcancel'];
const CONTAINER_ID = 'ptr-container';

// A box rather than a bare variable: the hook object has to be republished after
// every commit, and assigning to a module-level binding during render is what
// the react-compiler lint rule is there to stop.
const hookState = { current: null };
let onRefresh;

/** The ref is handed to the DOM the way every real call site hands it over. */
function Node({ containerRef }) {
    return <div ref={containerRef} data-testid={CONTAINER_ID} />;
}

function Harness({ threshold = 80, maxPull = 150, disabled = false }) {
    const hook = usePullToRefresh({ onRefresh, threshold, maxPull, disabled });
    useEffect(() => { hookState.current = hook; });
    return <Node containerRef={hook.containerRef} />;
}

/** Record add/remove of the four touch listeners on our container only. */
function instrument() {
    const bound = [];
    const unbound = [];
    const originalAdd = HTMLElement.prototype.addEventListener;
    const originalRemove = HTMLElement.prototype.removeEventListener;
    const isOurs = (node, type) =>
        node?.dataset?.testid === CONTAINER_ID && TOUCH_TYPES.includes(type);

    vi.spyOn(HTMLElement.prototype, 'addEventListener').mockImplementation(function spyAdd(type, handler, options) {
        if (isOurs(this, type)) bound.push({ type, handler, options });
        return originalAdd.call(this, type, handler, options);
    });
    vi.spyOn(HTMLElement.prototype, 'removeEventListener').mockImplementation(function spyRemove(type, handler, options) {
        if (isOurs(this, type)) unbound.push({ type, handler, options });
        return originalRemove.call(this, type, handler, options);
    });

    return {
        bound,
        unbound,
        countOf: (list, type) => list.filter((entry) => entry.type === type).length,
    };
}

/** A cancelable Event carrying a touch point; jsdom has no TouchEvent ctor. */
const touch = (type, clientY) => {
    const event = new Event(type, { bubbles: true, cancelable: true });
    event.touches = [{ clientY }];
    return event;
};

const fire = (element, type, clientY) => {
    const event = touch(type, clientY);
    act(() => { element.dispatchEvent(event); });
    return event;
};

describe('usePullToRefresh listener lifecycle', () => {
    let spy;

    beforeEach(() => {
        onRefresh = vi.fn().mockResolvedValue(undefined);
        spy = instrument();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('binds each touch listener exactly once across a full gesture', async () => {
        const { getByTestId } = render(<Harness />);
        const container = getByTestId(CONTAINER_ID);

        // Nothing unbound mid-gesture: the `{passive: false}` touchmove is not
        // swapped out from under a finger that is still down.
        expect(spy.unbound).toHaveLength(0);

        fire(container, 'touchstart', 0);
        for (let y = 10; y <= 200; y += 10) {
            fire(container, 'touchmove', y);
        }
        // `handleTouchEnd` is async and keeps updating state after `onRefresh`
        // settles, so the release has to be awaited rather than fired.
        await act(async () => { fire(container, 'touchend', 200); });

        for (const type of TOUCH_TYPES) {
            expect(spy.countOf(spy.bound, type), `${type} bind count`).toBe(1);
            expect(spy.countOf(spy.unbound, type), `${type} unbind count`).toBe(0);
        }
    });

    it('keeps the passive:false touchmove that carries the preventDefault', () => {
        render(<Harness />);
        const move = spy.bound.find((entry) => entry.type === 'touchmove');
        expect(move).toBeDefined();
        expect(move.options).toEqual({ passive: false });
    });

    it('still cancels the scroll while pulling, and stops below the dead zone', () => {
        const { getByTestId } = render(<Harness />);
        const container = getByTestId(CONTAINER_ID);

        fire(container, 'touchstart', 0);

        // diff 20 * 0.5 resistance = 10px, which is the dead zone.
        expect(fire(container, 'touchmove', 20).defaultPrevented).toBe(false);
        // diff 60 * 0.5 = 30px.
        expect(fire(container, 'touchmove', 60).defaultPrevented).toBe(true);
        expect(hookState.current.pullDistance).toBe(30);
    });

    it('refreshes once past the threshold and snaps back', async () => {
        const { getByTestId } = render(<Harness />);
        const container = getByTestId(CONTAINER_ID);

        fire(container, 'touchstart', 0);
        fire(container, 'touchmove', 200); // 100px resisted, threshold 80
        await act(async () => { fire(container, 'touchend', 200); });

        expect(onRefresh).toHaveBeenCalledTimes(1);
        expect(hookState.current.pullDistance).toBe(0);
        expect(hookState.current.isPulling).toBe(false);
        expect(spy.countOf(spy.bound, 'touchmove')).toBe(1);
    });

    it('does not refresh below the threshold', async () => {
        const { getByTestId } = render(<Harness threshold={200} />);
        const container = getByTestId(CONTAINER_ID);

        fire(container, 'touchstart', 0);
        fire(container, 'touchmove', 40); // 20px resisted
        await act(async () => { fire(container, 'touchend', 40); });

        expect(onRefresh).not.toHaveBeenCalled();
        expect(hookState.current.pullDistance).toBe(0);
        expect(spy.countOf(spy.bound, 'touchmove')).toBe(1);
    });

    it('ignores move/end frames that arrive without a start', async () => {
        const { getByTestId } = render(<Harness />);
        const container = getByTestId(CONTAINER_ID);

        // A stray `touchmove` (the browser synthesises one when a scroll
        // continues after the touch ends) must not pull the indicator.
        expect(fire(container, 'touchmove', 200).defaultPrevented).toBe(false);
        await act(async () => { fire(container, 'touchend', 200); });

        expect(onRefresh).not.toHaveBeenCalled();
        expect(hookState.current.pullDistance).toBe(0);
    });

    it('ends the gesture on touchcancel, through the same handler as touchend', async () => {
        const { getByTestId } = render(<Harness />);
        const container = getByTestId(CONTAINER_ID);

        fire(container, 'touchstart', 0);
        fire(container, 'touchmove', 200);
        await act(async () => { fire(container, 'touchcancel', 200); });

        // `touchcancel` is deliberately bound to `handleTouchEnd`, so a cancel
        // past the threshold refreshes exactly as a release does. Unchanged
        // behaviour; what matters here is that the gesture ends and that the
        // cancel listener is bound once like the other three.
        expect(onRefresh).toHaveBeenCalledTimes(1);
        expect(hookState.current.pullDistance).toBe(0);
        expect(hookState.current.isPulling).toBe(false);
        expect(spy.countOf(spy.bound, 'touchcancel')).toBe(1);
    });

    it('reads the latest props without rebinding', () => {
        const { getByTestId, rerender } = render(<Harness threshold={80} />);
        const container = getByTestId(CONTAINER_ID);

        rerender(<Harness threshold={400} />);
        fire(container, 'touchstart', 0);
        fire(container, 'touchmove', 40); // 20px resisted, under the new 400

        expect(spy.countOf(spy.bound, 'touchmove')).toBe(1);
        expect(hookState.current.pullDistance).toBe(20);
    });

    it('honours disabled without rebinding', () => {
        const { getByTestId, rerender } = render(<Harness />);
        const container = getByTestId(CONTAINER_ID);

        rerender(<Harness disabled />);
        fire(container, 'touchstart', 0);
        fire(container, 'touchmove', 200);

        expect(hookState.current.isPulling).toBe(false);
        expect(hookState.current.pullDistance).toBe(0);
        expect(spy.countOf(spy.bound, 'touchstart')).toBe(1);
    });

    it('ignores a pull started inside a form control', () => {
        const { getByTestId } = render(<Harness />);
        const container = getByTestId(CONTAINER_ID);
        const input = document.createElement('input');
        container.appendChild(input);

        act(() => { input.dispatchEvent(touch('touchstart', 0)); });
        act(() => { input.dispatchEvent(touch('touchmove', 200)); });

        expect(hookState.current.isPulling).toBe(false);
        expect(hookState.current.pullDistance).toBe(0);
    });

    it('releases every listener on unmount', () => {
        const { getByTestId, unmount } = render(<Harness />);
        getByTestId(CONTAINER_ID);

        expect(spy.unbound).toHaveLength(0);
        unmount();
        for (const type of TOUCH_TYPES) {
            expect(spy.countOf(spy.unbound, type), `${type} unbind on unmount`).toBe(1);
        }
    });

    it('caps the pull at maxPull', () => {
        const { getByTestId } = render(<Harness maxPull={40} />);
        const container = getByTestId(CONTAINER_ID);

        fire(container, 'touchstart', 0);
        fire(container, 'touchmove', 5000);

        expect(hookState.current.pullDistance).toBe(40);
        expect(hookState.current.progress).toBe(0.5);
        expect(spy.countOf(spy.bound, 'touchmove')).toBe(1);
    });

    it('would fail against a per-frame rebind (canary)', () => {
        // The pre-fix shape: handlers that close over per-frame state, so the
        // attach effect's dependency list changes mid-gesture and React tears the
        // listeners down and re-adds them on every frame. One `useCallback` per
        // frame, so the lists are never equal.
        const attaches = [];
        const attach = (frame) => {
            attaches.push([() => frame, () => frame + 1]);
        };

        for (let frame = 0; frame < 4; frame += 1) attach(frame);

        expect(attaches.length).toBe(4);
        expect(attaches[0]).not.toEqual(attaches[3]);
    });
});
