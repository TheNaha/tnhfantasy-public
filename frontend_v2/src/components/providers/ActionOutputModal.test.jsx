import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import ActionOutputModal from './ActionOutputModal';

describe('ActionOutputModal', () => {
    it('renders null when output is null', () => {
        const { container } = render(<ActionOutputModal output={null} onClose={vi.fn()} />);
        expect(container.firstChild).toBeNull();
    });

    it('renders success output with details and copy button', () => {
        const onClose = vi.fn();
        render(
            <ActionOutputModal
                output={{
                    title: 'Setup: modal-1',
                    status: 'success',
                    message: 'Setup completed successfully',
                    details: '{"status": "ok", "volumes": ["models"]}',
                }}
                onClose={onClose}
            />
        );

        expect(screen.getByRole('dialog', { name: /Setup: modal-1/i })).toBeInTheDocument();
        expect(screen.getByText('Setup completed successfully')).toBeInTheDocument();
        expect(screen.getByText(/volumes/i)).toBeInTheDocument();

        // Close button
        const closeBtn = screen.getByRole('button', { name: /^Close$/i });
        fireEvent.click(closeBtn);
        expect(onClose).toHaveBeenCalled();
    });

    it('renders failed status banner when action fails', () => {
        render(
            <ActionOutputModal
                output={{
                    title: 'Setup: modal-error',
                    status: 'failed',
                    message: 'In-process setup timed out',
                    details: 'Error: timeout after 30s',
                }}
                onClose={vi.fn()}
            />
        );

        expect(screen.getByText('In-process setup timed out')).toBeInTheDocument();
        expect(screen.getByText(/Error: timeout after 30s/i)).toBeInTheDocument();
    });
});
