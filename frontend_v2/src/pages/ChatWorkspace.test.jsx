import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatWorkspace from './ChatWorkspace';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

Element.prototype.scrollIntoView = vi.fn();

const mockActiveChatId = vi.hoisted(() => vi.fn(() => 'chat-1'));
const mockStreamingJobs = vi.hoisted(() => vi.fn(() => ({})));
const mockSetActiveChat = vi.hoisted(() => vi.fn());
const mockUpdateStreamingJob = vi.hoisted(() => vi.fn());
const mockClearStreamingJob = vi.hoisted(() => vi.fn());
const mockSelectedLorebooks = vi.hoisted(() => vi.fn(() => []));
const mockToggleLorebook = vi.hoisted(() => vi.fn());

vi.mock('../store/worldVaultStore', () => ({
    useWorldVaultStore: (sel) =>
        sel({
            activeChatId: mockActiveChatId(),
            streamingJobs: mockStreamingJobs(),
            setActiveChat: mockSetActiveChat,
            updateStreamingJob: mockUpdateStreamingJob,
            clearStreamingJob: mockClearStreamingJob,
            contextBuilder: { selectedLorebooks: [], systemPromptOverride: null, maxContextTokens: 4096 },
            selectedLorebooks: mockSelectedLorebooks(),
            toggleLorebook: mockToggleLorebook,
        }),
}));

const mockChats = vi.hoisted(() => vi.fn());
const mockMessages = vi.hoisted(() => vi.fn());
const mockSendMessage = vi.hoisted(() => vi.fn());
const mockCreateChat = vi.hoisted(() => vi.fn());
const mockDeleteChat = vi.hoisted(() => vi.fn());
const mockRenameChat = vi.hoisted(() => vi.fn());
const mockCharacters = vi.hoisted(() => vi.fn());
const mockLorebooks = vi.hoisted(() => vi.fn());
const mockUpdateChat = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useWorldVault', () => ({
    useChats: (...a) => mockChats(...a),
    useMessages: (...a) => mockMessages(...a),
    useSendMessage: (...a) => mockSendMessage(...a),
    useCreateChat: (...a) => mockCreateChat(...a),
    useDeleteChat: (...a) => mockDeleteChat(...a),
    useRenameChat: (...a) => mockRenameChat(...a),
    useUpdateChat: (...a) => mockUpdateChat(...a),
    useCharacters: (...a) => mockCharacters(...a),
    useLorebooks: (...a) => mockLorebooks(...a),
    useChat: () => ({ data: null }),
    useDeleteMessage: () => ({ mutateAsync: vi.fn() }),
    useSuggestReply: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useLLMAvailableModels: () => ({ data: [{ id: 'gpt-test', name: 'gpt-test' }] }),
    useLLMDefaultProvider: () => ({ data: { provider_id: 'llm-local', model_id: 'default' } }),
    useChatSystemPrompt: () => ({ data: { system_prompt: 'test system prompt', has_override: false } }),
    useEditMessage: () => ({ mutateAsync: vi.fn() }),
    useRollbackChat: () => ({ mutateAsync: vi.fn() }),
    useRegenerateReply: () => ({ mutateAsync: vi.fn() }),
    useChatJobs: () => ({ data: [] }),
    useCharacterCollection: () => ({ data: { images: [], image_count: 0 } }),
    usePatchCharacter: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useImpersonateMessage: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    usePinMessage: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useSwipeMessage: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    getAvatarUrl: () => '',
}));

vi.mock('../api', () => ({
    worldVaultApi: {
        chats: { sendMessage: vi.fn(), update: vi.fn() },
        upload: { chatAttachment: vi.fn() },
    },
}));

vi.mock('../api/websocket', () => ({
    useWebSocket: () => ({ subscribe: vi.fn(() => vi.fn()), unsubscribe: vi.fn() }),
    EventTypes: { JOB_PROGRESS: 'job.progress', JOB_COMPLETED: 'job.completed', JOB_FAILED: 'job.failed' },
}));

vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn(), promise: vi.fn() },
}));

vi.mock('framer-motion', () => ({
    motion: {
        div: ({ children, ...props }) => <div {...filterMotionProps(props)}>{children}</div>,
        button: ({ children, ...props }) => <button {...filterMotionProps(props)}>{children}</button>,
    },
    AnimatePresence: ({ children }) => <>{children}</>,
}));

function filterMotionProps(props) {
    const safe = {};
    for (const k of Object.keys(props)) {
        if (!['initial', 'animate', 'exit', 'whileHover', 'whileTap', 'transition', 'variants', 'layout'].includes(k)) {
            safe[k] = props[k];
        }
    }
    return safe;
}

function renderWithProviders(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>{ui}</MemoryRouter>
        </QueryClientProvider>
    );
}

describe('ChatWorkspace page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockChats.mockReturnValue({ data: [{ id: 'chat-1', name: 'Test Chat', character_id: null }], isLoading: false });
        mockMessages.mockReturnValue({ data: [], isLoading: false });
        mockSendMessage.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ user_message_id: 'msg-1', job_id: null }) });
        mockCreateChat.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ id: 'chat-2' }) });
        mockDeleteChat.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockRenameChat.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockCharacters.mockReturnValue({ data: [], isLoading: false });
        mockLorebooks.mockReturnValue({ data: [], isLoading: false });
    });

    it('renders the chat workspace layout', () => {
        renderWithProviders(<ChatWorkspace />);
        expect(screen.getByPlaceholderText(/Type a message/)).toBeInTheDocument();
    });

    it('displays chat list in sidebar', () => {
        renderWithProviders(<ChatWorkspace />);
        expect(screen.getByText('Test Chat')).toBeInTheDocument();
    });

    it('shows message input area', () => {
        renderWithProviders(<ChatWorkspace />);
        const textarea = screen.getByPlaceholderText(/Type a message/);
        expect(textarea).toBeInTheDocument();
        expect(textarea.tagName).toBe('TEXTAREA');
    });

    it('shows loading state while chats are loading', () => {
        mockChats.mockReturnValue({ data: [], isLoading: true });
        const { container } = renderWithProviders(<ChatWorkspace />);
        expect(container.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('shows empty messages area when no chat selected', () => {
        mockActiveChatId.mockReturnValue(null);
        renderWithProviders(<ChatWorkspace />);
        expect(screen.getByText(/Select a chat or create a new one to begin your roleplay/)).toBeInTheDocument();
    });

    it('renders the Chats sidebar header', () => {
        renderWithProviders(<ChatWorkspace />);
        expect(screen.getAllByText('Chats').length).toBeGreaterThan(0);
    });
});
