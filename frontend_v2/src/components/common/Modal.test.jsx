import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Modal } from './Modal';

describe('Modal', () => {
    it('renders nothing when closed', () => {
        const { container } = render(
            <Modal isOpen={false} onClose={() => {}} title="Hidden">
                <div>body</div>
            </Modal>
        );
        expect(container.querySelector('.fixed')).toBeNull();
    });

    it('renders title, body, and close button when open', () => {
        render(
            <Modal isOpen onClose={() => {}} title="My Modal">
                <div>modal body</div>
            </Modal>
        );
        expect(screen.getByText('My Modal')).toBeTruthy();
        expect(screen.getByText('modal body')).toBeTruthy();
        expect(screen.getByLabelText('Close modal')).toBeTruthy();
    });

    it('calls onClose on Escape', () => {
        const onClose = vi.fn();
        render(
            <Modal isOpen onClose={onClose} title="Esc">
                <div>body</div>
            </Modal>
        );
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('calls onClose when backdrop clicked and stopPropagation on panel', () => {
        const onClose = vi.fn();
        render(
            <Modal isOpen onClose={onClose} title="Backdrop">
                <div>body</div>
            </Modal>
        );
        const backdrop = document.querySelector('.fixed.inset-0');
        fireEvent.click(backdrop);
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('does not close on backdrop click when closeOnBackdrop is false', () => {
        const onClose = vi.fn();
        render(
            <Modal isOpen onClose={onClose} title="Locked" closeOnBackdrop={false}>
                <div>body</div>
            </Modal>
        );
        fireEvent.click(document.querySelector('.fixed.inset-0'));
        expect(onClose).not.toHaveBeenCalled();
    });
});
