import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import RelationshipTimeline from './RelationshipTimeline';

const mockApi = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('../api/client', () => ({ api: mockApi }));

const mockCharacters = [
    { id: 'char-1', name: 'Alice' },
    { id: 'char-2', name: 'Bob' },
];

const mockChats = [
    {
        id: 'chat-1',
        name: 'Secret Mission',
        character_id: 'char-1',
        additional_character_ids: ['char-2'],
    },
];

vi.mock('../hooks/useCharacters', () => ({
    useCharacters: () => ({
        data: mockCharacters,
        isLoading: false,
        isError: false,
    }),
}));

vi.mock('../hooks/useChats', () => ({
    useChats: () => ({
        data: mockChats,
        isLoading: false,
        isError: false,
    }),
}));

describe('RelationshipTimeline', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('loads and displays messages when api returns a raw array', async () => {
        mockApi.get.mockResolvedValueOnce([
            {
                id: 'm1',
                sender_name: 'Alice',
                content: 'Hello Bob!',
                created_at: '2026-11-04T12:00:00Z',
            },
        ]);

        render(<RelationshipTimeline />);

        const selects = screen.getAllByRole('combobox');
        fireEvent.change(selects[0], { target: { value: 'char-1' } });
        fireEvent.change(selects[1], { target: { value: 'char-2' } });

        await waitFor(() => {
            expect(mockApi.get).toHaveBeenCalledWith(
                '/api/v2/chats/chat-1/messages',
                { params: { limit: 200 } }
            );
            expect(screen.getByText('Hello Bob!')).toBeInTheDocument();
        });
    });

    it('loads and displays messages when api returns an object with messages array', async () => {
        mockApi.get.mockResolvedValueOnce({
            messages: [
                {
                    id: 'm2',
                    sender_name: 'Bob',
                    content: 'Hey Alice!',
                    created_at: '2026-11-04T12:05:00Z',
                },
            ],
        });

        render(<RelationshipTimeline />);

        const selects = screen.getAllByRole('combobox');
        fireEvent.change(selects[0], { target: { value: 'char-1' } });
        fireEvent.change(selects[1], { target: { value: 'char-2' } });

        await waitFor(() => {
            expect(screen.getByText('Hey Alice!')).toBeInTheDocument();
        });
    });
});
