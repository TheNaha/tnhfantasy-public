import { create } from 'zustand';

const DEFAULT_STATE = {
    isOpen: false,
    title: 'Confirm Action',
    message: 'Are you sure you want to proceed?',
    confirmText: 'Confirm',
    cancelText: 'Cancel',
    isDangerous: false,
    resolver: null,
};

export const useConfirmationStore = create((set, get) => ({
    ...DEFAULT_STATE,

    /**
     * Ask the user to confirm something, and resolve with their answer.
     *
     * One dialog, one pending resolver — so a second `openConfirmation` before
     * the first is answered has to settle the first. It used to just overwrite
     * `resolver`, which orphaned the earlier promise permanently: nothing
     * anywhere held it, so its `await` never returned. `useDashboardSelection`
     * awaits `confirm()` at the top of both its bulk handlers, so a
     * delete-then-download on a double click left the second modal showing and
     * every awaiting handler below it stuck — with no error and no toast, since
     * a promise that never settles reports nothing at all.
     *
     * Resolving the superseded one `false` is the answer the user actually gave
     * the superseded question, as far as anyone can tell: they never confirmed
     * it. Queueing instead would need a stack in the store and a UI that
     * renders the head of it; nothing needs the second behaviour today, and
     * declining is the safe default for a destructive action.
     */
    openConfirmation: (options = {}) => {
        const { resolver: pending } = get();
        if (pending) {
            pending(false);
        }
        return new Promise((resolve) => {
            set({
                isOpen: true,
                title: options.title || DEFAULT_STATE.title,
                message: options.message || DEFAULT_STATE.message,
                confirmText: options.confirmText || DEFAULT_STATE.confirmText,
                cancelText: options.cancelText || DEFAULT_STATE.cancelText,
                isDangerous: Boolean(options.isDangerous),
                resolver: resolve,
            });
        });
    },

    resolveConfirmation: (accepted) => {
        const { resolver } = get();
        if (resolver) {
            resolver(Boolean(accepted));
        }
        set({
            ...DEFAULT_STATE,
        });
    },
}));

export function useConfirmation() {
    const openConfirmation = useConfirmationStore((state) => state.openConfirmation);
    return { confirm: openConfirmation };
}
