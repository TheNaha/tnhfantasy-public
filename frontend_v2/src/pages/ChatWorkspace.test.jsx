import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChatWorkspace from './ChatWorkspace';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

Element.prototype.scrollIntoView = vi.fn();

const mockActiveChatId = vi.hoisted(() => vi.fn(() => 'chat-1'));
// `MemoryRouter` swallows navigation, so the URL change is observed at the
// `useNavigate` boundary — which is also the unit the fix changed.
const mockNavigate = vi.hoisted(() => vi.fn());
const mockSetActiveChat = vi.hoisted(() => vi.fn());
const addImagesToCollectionMock = vi.hoisted(() => vi.fn().mockResolvedValue({}));

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../store/worldVaultStore', () => ({
    useWorldVaultStore: (sel) =>
        sel({
            activeChatId: mockActiveChatId(),
            setActiveChat: mockSetActiveChat,
        }),
}));

// Streaming-job state now lives in React Query (useStreamingJobs). The mock
// returns an empty active-stream list so ChatWorkspace renders the "no stream"
// path; set/clear helpers are no-ops.
const mockSetStreamingJob = vi.fn();
const mockClearStreamingJob = vi.fn();
const mockGetStreamingJob = vi.fn(() => undefined);
vi.mock('../hooks/useStreamingJobs', () => ({
    useActiveChatStreams: vi.fn(() => []),
    setStreamingJob: (...args) => mockSetStreamingJob(...args),
    clearStreamingJob: (...args) => mockClearStreamingJob(...args),
    getStreamingJob: (...args) => mockGetStreamingJob(...args),
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
const mockExportChatToStory = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useWorldVault', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useChats: (...a) => mockChats(...a),
        useMessages: (...a) => mockMessages(...a),
        useSendMessage: (...a) => mockSendMessage(...a),
    useCreateChat: (...a) => mockCreateChat(...a),
    useDeleteChat: (...a) => mockDeleteChat(...a),
    useRenameChat: (...a) => mockRenameChat(...a),
    useUpdateChat: (...a) => mockUpdateChat(...a),
    useCharacters: (...a) => mockCharacters(...a),
    useLorebooks: (...a) => mockLorebooks(...a),
    useWorlds: () => ({ data: [] }),
    usePersonas: () => ({ data: [] }),
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
    useBranches: () => ({ data: [], isLoading: false }),
    useCreateBranch: () => ({ mutate: vi.fn() }),
    useChatImages: () => ({ data: [] }),
    usePatchCharacter: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useImpersonateMessage: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    usePinMessage: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useSwipeMessage: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useGenerateSwipe: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useNarrateMessage: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useIllustrateChat: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useGenerateScene: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSearchChats: () => ({ data: [] }),
    useExportChatJsonl: () => ({ mutateAsync: vi.fn(async () => ({ blob: new Blob(), filename: 'chat.jsonl' })), isPending: false }),
    useExportChatToStory: (...a) => mockExportChatToStory(...a),
    useImportChat: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useEvaluateChatDirector: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useUpdateChatStateSnapshot: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useCommitChatToCanon: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useCompileChatToStory: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useRunWorldTick: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useReverseVisionSync: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useChatDirectorStream: () => ({ directorState: null, isEvaluating: false }),
    useActiveLorebooks: () => ({ data: [] }),
    getAvatarUrl: () => '',
    };
});

// The new-chat wizard picks the chat's Location from the library, so the
// create payload can finally carry `location_id` — the column the Locations
// page and the prompt's [Location: …] block depend on. `LocationModal` is
// mounted alongside it and calls the create/update hooks before its own
// `isOpen` early return, so they have to exist on the mock too.
vi.mock('../hooks/useLocations', () => ({
    useLocations: () => ({ data: [{ id: 'loc-1', name: 'The Docks' }] }),
    useCreateLocation: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
    useUpdateLocation: () => ({ mutateAsync: vi.fn(), mutate: vi.fn() }),
}));

vi.mock('../api', () => ({
    filesApi: {
        uploadChatAttachment: vi.fn(),
    },
}));
vi.mock('../hooks/useCollections', () => ({
    useCollections: () => ({ data: {} }),
    // The context saves chat images through this mutation rather than calling
    // `addImagesToCollection` directly, so the hook owns the invalidation
    // policy for both the collection list and the per-character collection
    // query. Mocking the mutation (not the raw API function) keeps the test
    // honest about which layer the component depends on.
    useAddImagesToCollection: () => ({ mutateAsync: addImagesToCollectionMock }),
}));
vi.mock('../api/collectionsApi', () => ({
    addImagesToCollection: addImagesToCollectionMock,
}));

vi.mock('../api/websocket', () => ({
    useWebSocket: () => ({ subscribe: vi.fn(() => vi.fn()), unsubscribe: vi.fn() }),
    EventTypes: { JOB_PROGRESS: 'job.progress', JOB_COMPLETED: 'job.completed', JOB_FAILED: 'job.failed' },
}));

vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
    useConfirmationStore: { getState: vi.fn(), setState: vi.fn() },
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

function renderWithProviders(ui, routerProps = {}) {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter {...routerProps}>{ui}</MemoryRouter>
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
        mockExportChatToStory.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ story_id: 'story-1', title: 'Exported Story' }), isPending: false });
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

    it('sends a message when the send button is clicked', async () => {
        mockActiveChatId.mockReturnValue('chat-1');
        mockUpdateChat.mockReturnValue({ mutate: vi.fn() });
        const sendMsg = vi.fn().mockResolvedValue({ user_message_id: 'msg-1', job_id: null });
        mockSendMessage.mockReturnValue({ mutateAsync: sendMsg, isPending: false });

        renderWithProviders(<ChatWorkspace />);

        const textarea = screen.getByPlaceholderText(/Type a message/);
        fireEvent.change(textarea, { target: { value: 'Hello world' } });
        fireEvent.click(screen.getByLabelText('Send message'));

        await waitFor(() => {
            expect(sendMsg).toHaveBeenCalledWith(
                expect.objectContaining({
                    chatId: 'chat-1',
                    message: expect.objectContaining({ content: 'Hello world' }),
                })
            );
        });
    });

    it('deletes a chat via the sidebar context menu', async () => {
        const delChat = vi.fn().mockResolvedValue({});
        mockDeleteChat.mockReturnValue({ mutateAsync: delChat, isPending: false });

        renderWithProviders(<ChatWorkspace />);

        fireEvent.click(screen.getByLabelText('Delete chat'));

        await waitFor(() => {
            expect(delChat).toHaveBeenCalledWith('chat-1');
        });
    });

    // The URL is the single writer for which chat is open.
    //
    // These two used to fail, and the failure was silent. The context synced the
    // URL and the worldVault store in BOTH directions while every writer — the
    // sidebar click, the delete handler, new-chat, import — only set the store.
    // The URL always won, so selecting a different chat was reverted on the next
    // render (no error, no console warning, the item never highlighted), and
    // deleting the open chat pulled the selection back to the chat that had just
    // been deleted, whose queries then 404'd on every refetch.
    it('selecting a chat navigates instead of only writing the store', async () => {
        mockChats.mockReturnValue({
            data: [
                { id: 'chat-1', name: 'Test Chat', character_id: null },
                { id: 'chat-2', name: 'Second Chat', character_id: null },
            ],
            isLoading: false,
        });

        renderWithProviders(<ChatWorkspace />);

        fireEvent.click(screen.getByText('Second Chat'));

        // The store write alone is not the assertion — that is exactly what got
        // stomped. The navigation is the durable half, and it is the only thing
        // the URL-authoritative effect cannot undo.
        await waitFor(() => {
            expect(mockNavigate).toHaveBeenCalledWith('/chat/chat-2');
        });
    });

    it('deleting the open chat navigates away from the deleted id', async () => {
        // The loop. The handler moved the store to the next chat and the effect
        // pulled it back to the deleted one, so the workspace loaded a chat that
        // no longer existed.
        const delChat = vi.fn().mockResolvedValue({});
        mockDeleteChat.mockReturnValue({ mutateAsync: delChat, isPending: false });
        mockChats.mockReturnValue({
            data: [
                { id: 'chat-1', name: 'Test Chat', character_id: null },
                { id: 'chat-survivor', name: 'Survivor', character_id: null },
            ],
            isLoading: false,
        });

        renderWithProviders(<ChatWorkspace />);

        // Cleared here, not in `beforeEach`: with no `:id` route param the
        // bootstrap effect navigates to the open chat on mount, and that is
        // unrelated to the delete under test. Asserting over the full call log
        // therefore measured the wrong thing.
        mockNavigate.mockClear();

        // Scoped to the first row: two chats means two "Delete chat" buttons,
        // and the one under test is the open one.
        fireEvent.click(screen.getAllByLabelText('Delete chat')[0]);
        await waitFor(() => expect(delChat).toHaveBeenCalledWith('chat-1'));

        const destinations = mockNavigate.mock.calls.map((c) => String(c[0]));
        expect(destinations.some((d) => d.endsWith('/chat-1'))).toBe(false);
        expect(destinations).toContain('/chat/chat-survivor');
    });

    it('creates a chat with the location it was given, not just its name', async () => {
        const createChat = vi.fn().mockResolvedValue({ id: 'chat-2', world_id: null });
        // `confirmCreateChat` goes through `mutate` with an onSuccess callback
        // when the character has no alternate greetings, so both are the same
        // spy here rather than the call being recorded somewhere unasserted.
        mockCreateChat.mockReturnValue({ mutate: createChat, mutateAsync: createChat, isPending: false });

        renderWithProviders(<ChatWorkspace />, { initialEntries: ['/chat/chat-1?new=1'] });

        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
        fireEvent.change(screen.getByTestId('new-chat-location-select'), { target: { value: 'loc-1' } });
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
        fireEvent.click(screen.getByRole('button', { name: 'Create chat' }));

        await waitFor(() => expect(createChat).toHaveBeenCalled());
        expect(createChat.mock.calls[0][0]).toEqual(expect.objectContaining({
            location_id: 'loc-1',
            // the name still goes in, because it is the free-text column the
            // prompt's "Current Location:" line and the Activity filter read
            story_location: 'The Docks',
        }));
    });

    it('enters rename mode and updates chat name', async () => {
        const rename = vi.fn().mockResolvedValue({});
        mockRenameChat.mockReturnValue({ mutateAsync: rename, isPending: false });

        renderWithProviders(<ChatWorkspace />);

        fireEvent.click(screen.getByLabelText('Rename chat'));
        const renameInput = screen.getByDisplayValue('Test Chat');
        fireEvent.change(renameInput, { target: { value: 'Updated Chat' } });
        fireEvent.blur(renameInput);

        await waitFor(() => {
            expect(rename).toHaveBeenCalledWith(
                expect.objectContaining({ chatId: 'chat-1', name: 'Updated Chat' })
            );
        });
    });

    it('exports chat to Story Sandbox and navigates to the story', async () => {
        const exportFn = vi.fn().mockResolvedValue({ story_id: 'story-100', title: 'Exported Story' });
        mockExportChatToStory.mockReturnValue({ mutateAsync: exportFn, isPending: false });
        mockMessages.mockReturnValue({ data: [{ id: 'm-1', role: 'user', content: 'Hello' }], isLoading: false });

        renderWithProviders(<ChatWorkspace />);
        const exportBtn = screen.getByTitle('Export chat to Story Sandbox');
        fireEvent.click(exportBtn);

        await waitFor(() => expect(exportFn).toHaveBeenCalledWith('chat-1'));
        expect(mockNavigate).toHaveBeenCalledWith('/story/story-100');
    });
});
