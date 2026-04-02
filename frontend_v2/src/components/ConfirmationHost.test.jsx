import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import ConfirmationHost from './ConfirmationHost';
import { useConfirmationStore } from '../store/confirmationStore';

const DEFAULT_CONFIRMATION_STATE = {
    isOpen: false,
    title: 'Confirm Action',
    message: 'Are you sure you want to proceed?',
    confirmText: 'Confirm',
    cancelText: 'Cancel',
    isDangerous: false,
    resolver: null,
};

describe('ConfirmationHost', () => {
    beforeEach(() => {
        useConfirmationStore.setState({ ...DEFAULT_CONFIRMATION_STATE });
    });

    it('opens from store and resolves true on confirm', async () => {
        render(<ConfirmationHost />);

        let confirmationPromise;
        act(() => {
            confirmationPromise = useConfirmationStore.getState().openConfirmation({
                title: 'Delete Provider',
                message: 'Delete this provider?',
                confirmText: 'Delete',
                cancelText: 'Keep',
                isDangerous: true,
            });
        });

        expect(screen.getByText('Delete this provider?')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

        await expect(confirmationPromise).resolves.toBe(true);
        expect(useConfirmationStore.getState().isOpen).toBe(false);
    });

    it('opens from store and resolves false on cancel', async () => {
        render(<ConfirmationHost />);

        let confirmationPromise;
        act(() => {
            confirmationPromise = useConfirmationStore.getState().openConfirmation({
                title: 'Disable Provider',
                message: 'Disable this provider?',
                confirmText: 'Disable',
                cancelText: 'Cancel',
            });
        });

        expect(screen.getByText('Disable this provider?')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

        await expect(confirmationPromise).resolves.toBe(false);
        expect(useConfirmationStore.getState().isOpen).toBe(false);
    });
});
