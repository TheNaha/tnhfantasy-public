import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import CharacterAffinityHUD from './CharacterAffinityHUD';
import * as ChatWorkspaceContext from '../../contexts/ChatWorkspaceContext';

describe('CharacterAffinityHUD', () => {
    const mockChat = {
        id: 'chat-1',
        character_id: 'char-1',
        state_snapshot: {
            character_affinity: 65,
            last_affinity_delta: 2,
            character_mood: 'warm_affectionate',
            character_expression: 'smiling warmly',
            character_outfit: 'Silk traveler cloak',
            current_activity: 'Sharing tea by the campfire',
            relationship_status: 'Warming companions',
            inventory: ['Travel Journal', 'Iron Dagger'],
        },
    };

    const mockCharacter = {
        id: 'char-1',
        name: 'Aria',
        avatar_path: '/avatars/aria.png',
    };

    it('renders affinity score, mood badge, and inventory pills', async () => {
        vi.spyOn(ChatWorkspaceContext, 'useChatWorkspace').mockReturnValue({
            activeChat: mockChat,
            linkedCharacter: mockCharacter,
            activeStreams: [],
        });

        render(<CharacterAffinityHUD />);

        expect(screen.getByText('Affinity')).toBeInTheDocument();
        expect(screen.getByText('65')).toBeInTheDocument();
        expect(screen.getByText('Warm & Affectionate')).toBeInTheDocument();
        expect(screen.getByText('smiling warmly')).toBeInTheDocument();
        await waitFor(() => expect(screen.getByText('+2 Affection')).toBeInTheDocument());
        expect(screen.getByText('Travel Journal')).toBeInTheDocument();
    });

    it('expands status drawer on click to reveal attire, activity, and relationship details', () => {
        vi.spyOn(ChatWorkspaceContext, 'useChatWorkspace').mockReturnValue({
            activeChat: mockChat,
            linkedCharacter: mockCharacter,
            activeStreams: [],
        });

        render(<CharacterAffinityHUD />);

        const expandBtn = screen.getByRole('button', { name: /status/i });
        fireEvent.click(expandBtn);

        expect(screen.getByText('Warming companions')).toBeInTheDocument();
        expect(screen.getByText('Silk traveler cloak')).toBeInTheDocument();
        expect(screen.getByText('Sharing tea by the campfire')).toBeInTheDocument();
        expect(screen.getAllByText('Iron Dagger').length).toBeGreaterThanOrEqual(1);
    });

    it('returns null if activeChat is not present', () => {
        vi.spyOn(ChatWorkspaceContext, 'useChatWorkspace').mockReturnValue({
            activeChat: null,
            linkedCharacter: null,
            activeStreams: [],
        });

        const { container } = render(<CharacterAffinityHUD />);
        expect(container.firstChild).toBeNull();
    });
});
