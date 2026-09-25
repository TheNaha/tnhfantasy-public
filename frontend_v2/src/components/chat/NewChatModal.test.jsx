import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import NewChatModal from './NewChatModal';

describe('NewChatModal', () => {
    it('walks the beginner chat flow before creating', async () => {
        const onCreate = vi.fn().mockResolvedValue({});
        render(<NewChatModal characters={[]} lorebooks={[]} personas={[]} onCreate={onCreate} onClose={() => {}} />);

        expect(screen.getByRole('heading', { name: 'Create New Chat' })).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
        expect(screen.getByText('Character (Optional)')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
        expect(screen.getByText('No lorebooks yet. You can add one later from the World page.')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Create chat' }));

        await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ chatName: 'New Chat' })));
    });
});
