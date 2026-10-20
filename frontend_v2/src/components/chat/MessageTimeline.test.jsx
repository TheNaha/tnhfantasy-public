import React, { createRef } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mockUseChatWorkspace = vi.fn();
vi.mock('../../contexts/ChatWorkspaceContext', () => ({
    useChatWorkspace: () => mockUseChatWorkspace(),
}));
vi.mock('../../hooks/useVoices', () => ({ useVoices: () => ({ data: [] }) }));
vi.mock('./MessageItem', () => ({
    default: function Stub({ msg, linkedCharacter }) {
        return (
            <div data-testid="message-item" data-speaker={linkedCharacter?.id || ''}>
                {msg.content}
            </div>
        );
    },
}));
vi.mock('./TavernMessage', () => ({ default: ({ content }) => <span>{content}</span> }));

import MessageTimeline from './MessageTimeline';

const PRIMARY = { id: 'c1', name: 'Aria' };
const SECOND = { id: 'c2', name: 'Borin' };

/**
 * The pending-reply placeholder renders the Director HUD, which reads the
 * canonical gate registry — a query. React Query needs a client, so the
 * whole file renders inside one.
 */
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function renderTimeline() {
    return render(
        <QueryClientProvider client={queryClient}>
            <MessageTimeline />
        </QueryClientProvider>
    );
}

function makeContext(overrides = {}) {
    return {
        messages: [],
        listItems: [],
        rowVirtualizer: {
            getVirtualItems: () => [],
            getTotalSize: () => 0,
        },
        linkedCharacter: PRIMARY,
        activeChat: { id: 'chat-1' },
        characters: [PRIMARY, SECOND],
        targetCharacterId: '',
        settings: {},
        handleEditMessage: vi.fn(),
        handleDeleteMessage: vi.fn(),
        handleRegenerate: vi.fn(),
        handleRollback: vi.fn(),
        handlePinMessage: vi.fn(),
        handleSwipe: vi.fn(),
        handleGenerateSwipe: vi.fn(),
        handleAvatarClick: vi.fn(),
        handleGenerateTTS: vi.fn(),
        handleMessageIllustrate: vi.fn(),
        hasMoreMessages: false,
        loadOlderMessages: vi.fn(),
        messagesEndRef: createRef(),
        ...overrides,
    };
}

describe('MessageTimeline group-chat attribution', () => {
    beforeEach(() => {
        mockUseChatWorkspace.mockReset();
    });

    it('renders a message under its attributed character in group chats', () => {
        mockUseChatWorkspace.mockReturnValue(makeContext({
            messages: [{ id: 'm1', role: 'CHAR', content: 'From Borin', character_id: 'c2' }],
            listItems: [{ item: { id: 'm1', role: 'CHAR', content: 'From Borin', character_id: 'c2' } }],
            rowVirtualizer: { getVirtualItems: () => [{ index: 0 }], getTotalSize: () => 10 },
        }));

        renderTimeline();
        const rendered = screen.getByTestId('message-item');
        expect(rendered.dataset.speaker).toBe('c2');
    });

    it('falls back to the primary character when a message is untagged', () => {
        const msg = { id: 'm2', role: 'CHAR', content: 'Primary reply' };
        mockUseChatWorkspace.mockReturnValue(makeContext({
            messages: [msg],
            listItems: [{ item: msg }],
            rowVirtualizer: { getVirtualItems: () => [{ index: 0 }], getTotalSize: () => 10 },
        }));

        renderTimeline();
        expect(screen.getByTestId('message-item').dataset.speaker).toBe('c1');
    });

    it('shows the pending reply-as character in the streaming placeholder', () => {
        mockUseChatWorkspace.mockReturnValue(makeContext({
            targetCharacterId: 'c2',
            listItems: [{ jobId: 'j1', jobData: { taskType: 'text' } }],
            rowVirtualizer: { getVirtualItems: () => [{ index: 0 }], getTotalSize: () => 10 },
        }));

        renderTimeline();
        expect(screen.getByText(/Borin is thinking/)).toBeInTheDocument();
    });
});
