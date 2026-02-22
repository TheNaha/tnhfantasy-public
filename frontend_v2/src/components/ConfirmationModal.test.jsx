import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ConfirmationModal from './ConfirmationModal';

describe('ConfirmationModal', () => {
    it('renders when isOpen is true', () => {
        render(
            <ConfirmationModal
                isOpen={true}
                title="Test Title"
                message="Test Message"
                onConfirm={() => {}}
                onClose={() => {}}
            />
        );

        expect(screen.getByText('Test Title')).toBeInTheDocument();
        expect(screen.getByText('Test Message')).toBeInTheDocument();
        expect(screen.getByText('Confirm')).toBeInTheDocument();
        expect(screen.getByText('Cancel')).toBeInTheDocument();
    });

    it('does not render when isOpen is false', () => {
        render(
            <ConfirmationModal
                isOpen={false}
                title="Test Title"
                onConfirm={() => {}}
                onClose={() => {}}
            />
        );

        expect(screen.queryByText('Test Title')).not.toBeInTheDocument();
    });

    it('calls onConfirm when confirm button is clicked', () => {
        const handleConfirm = vi.fn();
        const handleClose = vi.fn();

        render(
            <ConfirmationModal
                isOpen={true}
                onConfirm={handleConfirm}
                onClose={handleClose}
            />
        );

        fireEvent.click(screen.getByText('Confirm'));

        expect(handleConfirm).toHaveBeenCalledTimes(1);
        expect(handleClose).toHaveBeenCalledTimes(1); // It calls cancel/close internally
    });

    it('calls onClose when cancel button is clicked', () => {
        const handleClose = vi.fn();

        render(
            <ConfirmationModal
                isOpen={true}
                onConfirm={() => {}}
                onClose={handleClose}
            />
        );

        fireEvent.click(screen.getByText('Cancel'));

        expect(handleClose).toHaveBeenCalledTimes(1);
    });

    it('renders custom button texts', () => {
        render(
            <ConfirmationModal
                isOpen={true}
                confirmText="Yes, do it"
                cancelText="No, wait"
                onConfirm={() => {}}
                onClose={() => {}}
            />
        );

        expect(screen.getByText('Yes, do it')).toBeInTheDocument();
        expect(screen.getByText('No, wait')).toBeInTheDocument();
    });
});
