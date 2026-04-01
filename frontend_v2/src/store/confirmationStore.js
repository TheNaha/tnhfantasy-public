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

    openConfirmation: (options = {}) => new Promise((resolve) => {
        set({
            isOpen: true,
            title: options.title || DEFAULT_STATE.title,
            message: options.message || DEFAULT_STATE.message,
            confirmText: options.confirmText || DEFAULT_STATE.confirmText,
            cancelText: options.cancelText || DEFAULT_STATE.cancelText,
            isDangerous: Boolean(options.isDangerous),
            resolver: resolve,
        });
    }),

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
