import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import ModalOverlay from './ModalOverlay';

describe('ModalOverlay', () => {
    // No manual document.body cleanup: the overlay portals into body, and
    // wiping body between tests leaves React unmounting nodes that are no
    // longer its children ("The node to be removed is not a child of this
    // node"). Testing Library's own cleanup handles it.

    it('renders children through a portal into document.body', () => {
        render(
            <ModalOverlay onClose={() => {}}>
                <button>inside panel</button>
            </ModalOverlay>,
        );
        // Portalled, so it is a child of body rather than the render container.
        expect(screen.getByText('inside panel')).toBeInTheDocument();
        expect(document.querySelector('[data-modal-overlay]')).not.toBeNull();
    });

    it('closes on Escape', () => {
        const onClose = vi.fn();
        render(
            <ModalOverlay onClose={onClose}>
                <div>panel</div>
            </ModalOverlay>,
        );

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('ignores keys other than Escape', () => {
        const onClose = vi.fn();
        render(<ModalOverlay onClose={onClose}><div>panel</div></ModalOverlay>);

        fireEvent.keyDown(window, { key: 'Enter' });
        fireEvent.keyDown(window, { key: 'a' });
        expect(onClose).not.toHaveBeenCalled();
    });

    it('closes on backdrop click', () => {
        const onClose = vi.fn();
        render(<ModalOverlay onClose={onClose}><div>panel</div></ModalOverlay>);

        fireEvent.click(document.querySelector('[data-modal-overlay]'));
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('closeOnBackdrop={false} disables the backdrop click', () => {
        const onClose = vi.fn();
        render(
            <ModalOverlay onClose={onClose} closeOnBackdrop={false}>
                <div>panel</div>
            </ModalOverlay>,
        );

        fireEvent.click(document.querySelector('[data-modal-overlay]'));
        expect(onClose).not.toHaveBeenCalled();
        // Escape must still work — a non-dismissible backdrop is not a
        // non-dismissible dialog.
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('renders nothing when isOpen is false, and binds no key listener', () => {
        const onClose = vi.fn();
        render(
            <ModalOverlay isOpen={false} onClose={onClose}>
                <div>panel</div>
            </ModalOverlay>,
        );

        expect(screen.queryByText('panel')).toBeNull();
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).not.toHaveBeenCalled();
    });

    it('removes its listener on unmount so a closed dialog cannot fire later', () => {
        const onClose = vi.fn();
        const { unmount } = render(
            <ModalOverlay onClose={onClose}><div>panel</div></ModalOverlay>,
        );

        unmount();
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).not.toHaveBeenCalled();
    });
});
