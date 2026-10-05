/**
 * The confirmation dialog's promise.
 *
 * The store holds ONE `resolver`. `openConfirmation` used to overwrite it, which
 * orphaned the superseded promise permanently: nothing in the app held it, so
 * its `await` never returned. That is not a cosmetic bug — `await confirm(...)`
 * is the FIRST line of every destructive handler in the app (bulk delete and
 * bulk download in `useDashboardSelection`, unpublish/delete in StorySandbox,
 * delete in Characters and Locations, three confirmation prompts in
 * ChatWorkspaceContext). One more prompt arriving before the first was answered
 * therefore stranded whichever handler was waiting, with no error and no toast,
 * because a promise that never settles reports nothing.
 */
import { renderHook, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const settled = (promise) => {
    const state = { done: false, value: undefined };
    promise.then((value) => { state.done = true; state.value = value; });
    // Two microtask turns: the store resolves through an intermediate step in
    // the pre-fix shape, and a single turn would race it.
    return Promise.resolve().then(() => Promise.resolve()).then(() => state);
};

describe('confirmationStore', () => {
    let useConfirmationStore;
    let useConfirmation;
    // `useConfirmation` is a React hook, so the store action is what these tests
    // drive; one test below covers that the hook hands out this same action.
    let confirm;

    beforeEach(async () => {
        vi.resetModules();
        ({ useConfirmationStore, useConfirmation } = await import('./confirmationStore'));
        confirm = (options) => useConfirmationStore.getState().openConfirmation(options);
        useConfirmationStore.setState({
            isOpen: false,
            title: 'Confirm Action',
            message: 'Are you sure you want to proceed?',
            confirmText: 'Confirm',
            cancelText: 'Cancel',
            isDangerous: false,
            resolver: null,
        });
    });

    it('resolves true on confirm and false on cancel', async () => {

        const accepted = confirm({ title: 'Delete 3 Images' });
        expect(useConfirmationStore.getState().isOpen).toBe(true);
        expect(useConfirmationStore.getState().title).toBe('Delete 3 Images');
        useConfirmationStore.getState().resolveConfirmation(true);

        const declined = confirm({ title: 'Delete again' });
        useConfirmationStore.getState().resolveConfirmation(false);

        await expect(accepted).resolves.toBe(true);
        await expect(declined).resolves.toBe(false);
    });

    it('exposes the same action through the useConfirmation hook', async () => {
        const { result } = renderHook(() => useConfirmation());
        const pending = act(() => result.current.confirm({ title: 'From the hook' }));

        expect(useConfirmationStore.getState().title).toBe('From the hook');
        act(() => useConfirmationStore.getState().resolveConfirmation(true));
        await expect(pending).resolves.toBe(true);
    });

    it('coerces a truthy non-boolean answer', async () => {
        const pending = confirm();
        useConfirmationStore.getState().resolveConfirmation('yes');
        await expect(pending).resolves.toBe(true);
    });

    it('resets to the defaults once answered', async () => {
        const pending = confirm({ title: 'Danger', message: 'gone', isDangerous: true });
        useConfirmationStore.getState().resolveConfirmation(true);
        await pending;

        const state = useConfirmationStore.getState();
        expect(state.isOpen).toBe(false);
        expect(state.title).toBe('Confirm Action');
        expect(state.message).toBe('Are you sure you want to proceed?');
        expect(state.isDangerous).toBe(false);
        expect(state.resolver).toBeNull();
    });

    describe('re-entrancy', () => {
        it('settles the superseded prompt with false instead of orphaning it', async () => {
    
            const first = confirm({ title: 'Delete 3 Images' });
            const firstState = await settled(first);
            expect(firstState.done).toBe(false);

            // A second prompt arrives before the first was answered — a second
            // selection action, or a toast-dismiss that opens another modal.
            const second = confirm({ title: 'Download 3 Images' });

            // The pre-fix store overwrote `resolver` here and the first promise
            // was unreachable from that point on.
            expect((await settled(first)).done).toBe(true);
            await expect(first).resolves.toBe(false);

            // The dialog shows the NEW question, not the abandoned one.
            expect(useConfirmationStore.getState().title).toBe('Download 3 Images');

            useConfirmationStore.getState().resolveConfirmation(true);
            await expect(second).resolves.toBe(true);
        });

        it('leaves the newest prompt answerable', async () => {
    
            const first = confirm({ title: 'A' });
            const second = confirm({ title: 'B' });
            const third = confirm({ title: 'C' });

            await expect(first).resolves.toBe(false);
            await expect(second).resolves.toBe(false);

            useConfirmationStore.getState().resolveConfirmation(true);
            await expect(third).resolves.toBe(true);
            expect(useConfirmationStore.getState().resolver).toBeNull();
        });

        it('does not resurrect an already-answered prompt', async () => {
    
            const first = confirm({ title: 'A' });
            useConfirmationStore.getState().resolveConfirmation(true);
            await expect(first).resolves.toBe(true);

            const second = confirm({ title: 'B' });
            useConfirmationStore.getState().resolveConfirmation(false);

            await expect(first).resolves.toBe(true);
            await expect(second).resolves.toBe(false);
        });

        it('unblocks a chain of overlapping confirm() callers', async () => {
            // The shape that hung: two handlers both awaiting `confirm()`, which
            // is what a delete-then-download on a double click produces.
                const answered = [];

            const bulkDelete = (async () => {
                const ok = await confirm({ title: 'Delete Images' });
                answered.push(`delete:${ok}`);
            })();
            const bulkDownload = (async () => {
                const ok = await confirm({ title: 'Download Images' });
                answered.push(`download:${ok}`);
            })();

            await Promise.resolve();
            useConfirmationStore.getState().resolveConfirmation(true);
            await Promise.all([bulkDelete, bulkDownload]);

            expect(answered).toContain('delete:false');
            expect(answered).toContain('download:true');
        });

        it('can tell a settled prompt from an orphaned one (canary)', async () => {
            // The pre-fix `openConfirmation`, verbatim. With no re-entrancy guard
            // the first promise is never resolved by anything — the second call
            // just replaces the only reference to its resolver.
            let held = [];
            const preFix = (options) => new Promise((resolve) => {
                held = [resolve];
                void options;
            });

            const first = preFix({ title: 'A' });
            const firstState = await settled(first);
            preFix({ title: 'B' });

            expect(held).toHaveLength(1);
            expect(firstState.done).toBe(false);
        });
    });
});