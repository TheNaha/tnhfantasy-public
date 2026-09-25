import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import RoleplayWorkspace from './RoleplayWorkspace';

vi.mock('../hooks/useChats', () => ({
    useChats: () => ({
        data: [{ id: 'chat-1', name: 'The First Meeting', updated_at: '2026-01-01T00:00:00Z' }],
        isLoading: false,
    }),
}));

vi.mock('../hooks/useStories', () => ({
    useStories: () => ({
        data: [{ id: 'story-1', title: 'A Small Beginning', updated_at: '2026-01-02T00:00:00Z' }],
        isLoading: false,
    }),
}));

vi.mock('../hooks/useCampaigns', () => ({
    useCampaigns: () => ({ data: [{ id: 'campaign-1', name: 'A Campaign' }] }),
}));

vi.mock('../hooks/useWorldVaultSearch', () => ({
    useWorldVaultDashboard: () => ({
        data: { counts: { characters: 2, chats: 1, stories: 1, lorebooks: 0, locations: 0 } },
    }),
}));

describe('RoleplayWorkspace', () => {
    it('offers simple entry points and recent sessions', () => {
        render(
            <MemoryRouter>
                <RoleplayWorkspace />
            </MemoryRouter>,
        );

        expect(screen.getByRole('heading', { name: /your next scene starts here/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /start a chat/i })).toBeInTheDocument();
        expect(screen.getByText('The First Meeting')).toBeInTheDocument();
        expect(screen.getByText('A Small Beginning')).toBeInTheDocument();
    });

    it('reveals expert world-building tools on demand', () => {
        render(
            <MemoryRouter>
                <RoleplayWorkspace />
            </MemoryRouter>,
        );

        expect(screen.queryByText('Lorebook')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /expert tools/i }));
        expect(screen.getByText('Lorebook')).toBeInTheDocument();
        expect(screen.getByText('World graph')).toBeInTheDocument();
    });
});
