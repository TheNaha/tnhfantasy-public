import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import toast from 'react-hot-toast';
import { awaitJobText } from '../hooks/useLLMJobResult';
import StorySandbox from './StorySandbox';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

Element.prototype.scrollIntoView = vi.fn();

const mockActiveStoryId = vi.hoisted(() => vi.fn(() => 'story-1'));
const mockSetActiveStory = vi.hoisted(() => vi.fn());

vi.mock('../store/worldVaultStore', () => ({
    useWorldVaultStore: (sel) =>
        sel({
            activeChatId: mockActiveStoryId(),
            setActiveChat: mockSetActiveStory,
        }),
}));

const mockStories = vi.hoisted(() => vi.fn());
const mockChapters = vi.hoisted(() => vi.fn());
const mockLorebooks = vi.hoisted(() => vi.fn());
const mockCreateStory = vi.hoisted(() => vi.fn());
const mockDeleteStory = vi.hoisted(() => vi.fn());
const mockUpdateStory = vi.hoisted(() => vi.fn());
const mockCreateChapter = vi.hoisted(() => vi.fn());
const mockDeleteChapter = vi.hoisted(() => vi.fn());
const mockUpdateChapter = vi.hoisted(() => vi.fn());
const mockContinueChapter = vi.hoisted(() => vi.fn());
const mockBranchChapter = vi.hoisted(() => vi.fn());
const mockAddStoryBeat = vi.hoisted(() => vi.fn());
const mockIllustrateChapter = vi.hoisted(() => vi.fn());
const mockStoryAiAction = vi.hoisted(() => vi.fn());
const mockUpdateStoryBeat = vi.hoisted(() => vi.fn());
const mockDeleteStoryBeat = vi.hoisted(() => vi.fn());
const mockPublishStory = vi.hoisted(() => vi.fn());
const mockStartChatFromStory = vi.hoisted(() => vi.fn());
const mockStory = vi.hoisted(() => vi.fn(() => ({ data: { id: 'story-1', title: 'My Story' } })));

vi.mock('../hooks/useWorldVault', () => ({
    useStories: (...a) => mockStories(...a),
    useStory: (...a) => mockStory(...a),
    useStoryChapters: (...a) => mockChapters(...a),
    useLorebooks: (...a) => mockLorebooks(...a),
    useCreateStory: (...a) => mockCreateStory(...a),
    useDeleteStory: (...a) => mockDeleteStory(...a),
    useUpdateStory: (...a) => mockUpdateStory(...a),
    useCreateChapter: (...a) => mockCreateChapter(...a),
    useDeleteChapter: (...a) => mockDeleteChapter(...a),
    useUpdateChapter: (...a) => mockUpdateChapter(...a),
    useReorderChapters: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
    useContinueChapter: (...a) => mockContinueChapter(...a),
    useBranchChapter: (...a) => mockBranchChapter(...a),
    useAddStoryBeat: (...a) => mockAddStoryBeat(...a),
    useIllustrateChapter: (...a) => mockIllustrateChapter(...a),
    useStoryAiAction: (...a) => mockStoryAiAction(...a),
    useRetryLastContinuation: () => ({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'job-1' }), isPending: false }),
    useUpdateStoryBeat: (...a) => mockUpdateStoryBeat(...a),
    useSelectStoryBeatAlternate: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
    useDeleteStoryBeat: (...a) => mockDeleteStoryBeat(...a),
    useChapterRevisions: () => ({ data: [], isLoading: false }),
    useCreateChapterRevision: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
    useRestoreChapterRevision: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
    useDiscoverWorldbuilding: () => ({ mutateAsync: vi.fn().mockResolvedValue({ discoveries: [] }), isPending: false }),
    useAdoptWorldbuilding: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
    // The story context panel's Scenario row lists the library, so the panel
    // can name what Apply attached instead of showing a bare id.
    useScenarios: () => ({ data: [] }),
    useCharacters: () => ({ data: [] }),
    useLocations: () => ({ data: [] }),
    useLLMAvailableModels: () => ({ data: [] }),
    useLLMDefaultProvider: () => ({ data: null }),
    useLLMRuntimeDefaults: () => ({ data: {} }),
    useStoryImages: () => ({ data: [] }),
    useUpdateCharacter: () => ({ mutateAsync: vi.fn() }),
    useParseStory: () => ({ mutateAsync: vi.fn() }),
    useExportStoryFormatted: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useExportPublishedStory: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useExportChapterComic: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    usePublishStory: () => mockPublishStory(),
    useUnpublishStory: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useNarrateChapter: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useStartChatFromStory: (...a) => mockStartChatFromStory(...a),
}));

vi.mock('../api/websocket', () => ({
    useWebSocket: () => ({ subscribe: vi.fn(() => vi.fn()), unsubscribe: vi.fn() }),
    getConnectionStatus: vi.fn(() => false),
    on: vi.fn(),
    EventTypes: { JOB_PROGRESS: 'job.progress', JOB_COMPLETED: 'job.completed', JOB_FAILED: 'job.failed', JOB_CANCELLED: 'job.cancelled' },
}));

vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: vi.fn(() => Promise.resolve(true)) }),
}));

vi.mock('../api', () => ({
    api: { put: vi.fn().mockResolvedValue({}) },
}));
vi.mock('../hooks/useLLMJobResult', () => ({
    useLLMJobResult: () => vi.fn().mockResolvedValue({ text: '', cancelled: false }),
    awaitJobText: vi.fn().mockResolvedValue({ jobId: 'job-1', text: 'A tight summary.' }),
}));
vi.mock('../hooks/useCollections', () => ({
    useCollections: () => ({ data: {} }),
}));
vi.mock('../api/collectionsApi', () => ({
    addImagesToCollection: vi.fn(),
}));

// `toast` is called as a FUNCTION for the copied-link message and as
// `toast.success` / `toast.error` elsewhere, so the default export has to be
// both — a plain `{success, error}` object threw on the function call and would
// have hidden the very branch these tests cover.
vi.mock('react-hot-toast', () => {
    const fn = vi.fn();
    fn.success = vi.fn();
    fn.error = vi.fn();
    return { default: fn, toast: fn };
});

vi.mock('framer-motion', () => ({
    motion: {
        div: ({ children, ...props }) => {
            const safe = {};
            for (const k of Object.keys(props)) {
                if (!['initial', 'animate', 'exit', 'whileHover', 'whileTap', 'transition', 'variants', 'layout'].includes(k)) {
                    safe[k] = props[k];
                }
            }
            return <div {...safe}>{children}</div>;
        },
        button: ({ children, ...props }) => {
            const safe = {};
            for (const k of Object.keys(props)) {
                if (!['initial', 'animate', 'exit', 'whileHover', 'whileTap', 'transition', 'variants', 'layout'].includes(k)) {
                    safe[k] = props[k];
                }
            }
            return <button {...safe}>{children}</button>;
        },
        span: ({ children }) => <span>{children}</span>,
        g: ({ children, ...props }) => {
            const safe = {};
            for (const k of Object.keys(props)) {
                if (!['initial', 'animate', 'exit', 'whileHover', 'whileTap', 'transition', 'variants', 'layout'].includes(k)) {
                    safe[k] = props[k];
                }
            }
            return <g {...safe}>{children}</g>;
        },
    },
    AnimatePresence: ({ children }) => <>{children}</>,
}));

function renderWithProviders(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            {/* StorySandbox reads storyId/chapterId from URL params; it must be
                mounted under a <Route> so useParams() reacts to navigate() —
                otherwise the auto-select effects can never drive the UI. */}
            <MemoryRouter initialEntries={['/story/story-1/chapter/ch-1']}>
                <Routes>
                    <Route path="/story" element={ui} />
                    <Route path="/story/:storyId" element={ui} />
                    <Route path="/story/:storyId/chapter/:chapterId" element={ui} />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>
    );
}

// The editor hydrates chapter prose on the next tick. AI-action tests must wait
// for it, otherwise the action modal opens with an empty selection (summarize
// falls back to the whole chapter) and the Generate button stays disabled.
const waitForEditorHydrated = () =>
    waitFor(() => {
        expect(
            screen.getAllByRole('textbox').some(el => el.value?.includes('Once upon a time'))
        ).toBe(true);
    }, { timeout: 3000 });

describe('StorySandbox page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockStories.mockReturnValue({
            data: [{ id: 'story-1', title: 'My Story', description: 'A fantasy epic', genre: 'Fantasy' }],
            isLoading: false,
        });
        mockChapters.mockReturnValue({
            data: [{ id: 'ch-1', story_id: 'story-1', chapter_number: 1, content: 'Once upon a time...', beats: [], image_paths: [] }],
            isLoading: false,
        });
        mockLorebooks.mockReturnValue({ data: [], isLoading: false });
        mockCreateStory.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ id: 'new-story' }) });
        mockDeleteStory.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockUpdateStory.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockCreateChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ id: 'new-ch' }) });
        mockDeleteChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockUpdateChapter.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue({}) });
        mockContinueChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'job-1' }) });
        mockBranchChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ id: 'branch-ch' }), isPending: false });
        mockAddStoryBeat.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockIllustrateChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'img-1' }) });
        mockStoryAiAction.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'job-1' }), isPending: false });
        // A full mutation object, not `{mutate}`: `ExportModal` reads
        // `isPending` off all four of its mutation hooks, and returning a
        // partial one crashed the render these tests drive.
        mockPublishStory.mockReturnValue({
            mutate: vi.fn(),
            mutateAsync: vi.fn(),
            isPending: false,
        });
        mockStartChatFromStory.mockReturnValue({
            mutate: vi.fn(),
            mutateAsync: vi.fn().mockResolvedValue({ chat_id: 'chat-1', title: 'Tale' }),
            isPending: false,
        });
    });

    it('renders the stories sidebar', () => {
        renderWithProviders(<StorySandbox />);
        expect(screen.getAllByText('Stories').length).toBeGreaterThan(0);
    });

    it('displays story list in sidebar', () => {
        renderWithProviders(<StorySandbox />);
        expect(screen.getByText('My Story')).toBeInTheDocument();
    });

    it('displays chapter list', () => {
        renderWithProviders(<StorySandbox />);
        expect(screen.getAllByText(/Chapter 1/).length).toBeGreaterThan(0);
    });

    it('shows editor with chapter content', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            const textareas = screen.getAllByRole('textbox');
            expect(textareas.some(el => el.value?.includes('Once upon a time'))).toBe(true);
        }, { timeout: 10000 });
        // 15000 rather than the previous 5000, and the inner waitFor raised from
        // 3000. Measured in isolation this test takes ~2.7 s to satisfy — so the
        // old 3000 ms `waitFor` had under 300 ms of headroom, and the suite runs
        // 157 files in parallel on one host. It passed in some full-suite runs
        // and failed in others with no code change in between, which is the
        // signature of a load-sensitive timeout rather than a defect.
        //
        // Same class as `backend_v2/tests/test_app_boot_smoke.py`, which starts
        // real threads and is the backend suite's known flake: a test whose
        // assertion is about *what* is rendered should not also be a measurement
        // of how fast the host is.
    }, 15000);

    it('shows loading state while fetching stories', () => {
        mockStories.mockReturnValue({ data: [], isLoading: true });
        mockChapters.mockReturnValue({ data: [], isLoading: false });
        const { container } = renderWithProviders(<StorySandbox />);
        expect(container.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('shows empty state when no stories', () => {
        mockStories.mockReturnValue({ data: [], isLoading: false });
        mockChapters.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<StorySandbox />);
        expect(screen.getByText(/no stories/i)).toBeInTheDocument();
    });

    it('renders the continue button', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByText('Continue')).toBeInTheDocument();
        });
    });

    it('renders the illustrate button', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByText('Illustrate')).toBeInTheDocument();
        });
    });

    it('renders the beat input area', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByPlaceholderText(/story beat/i)).toBeInTheDocument();
        });
    });

    it('continues story when Continue button is clicked', async () => {
        const mockMutate = vi.fn().mockResolvedValue({ job_id: 'job-continue' });
        mockContinueChapter.mockReturnValue({ mutateAsync: mockMutate, isPending: false });
        mockStories.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByText('Continue')).toBeInTheDocument();
        });
        await waitForEditorHydrated();
        fireEvent.click(screen.getByRole('button', { name: /continue/i }));
        expect(mockMutate).toHaveBeenCalledWith({
            storyId: 'story-1',
            chapterId: 'ch-1',
            prompt: '',
        });
    }, 10000);

    it('adds a story beat when beat text is entered and Add is clicked', async () => {
        const mockMutate = vi.fn().mockResolvedValue({});
        mockAddStoryBeat.mockReturnValue({ mutateAsync: mockMutate, isPending: false });
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByPlaceholderText(/story beat/i)).toBeInTheDocument();
        });
        const beatInput = screen.getByPlaceholderText(/story beat/i);
        fireEvent.change(beatInput, { target: { value: 'A new challenge arises' } });
        fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
        expect(mockMutate).toHaveBeenCalledWith({
            storyId: 'story-1',
            chapterId: 'ch-1',
            content: 'A new challenge arises',
            role: 'user',
        });
    }, 10000);

    it('adds a narrator-role beat when the role toggle is switched', async () => {
        const mockMutate = vi.fn().mockResolvedValue({});
        mockAddStoryBeat.mockReturnValue({ mutateAsync: mockMutate, isPending: false });
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByPlaceholderText(/story beat/i)).toBeInTheDocument();
        });
        fireEvent.click(screen.getByTitle(/Add as narrator prose/i));
        const beatInput = screen.getByPlaceholderText(/story beat/i);
        fireEvent.change(beatInput, { target: { value: 'Dark clouds gathered' } });
        fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
        expect(mockMutate).toHaveBeenCalledWith(
            expect.objectContaining({ content: 'Dark clouds gathered', role: 'narrator' })
        );
    }, 15000);

    it('edits a beat in place and saves through the update hook', async () => {
        const mockBeatUpdate = vi.fn().mockResolvedValue({});
        mockUpdateStoryBeat.mockReturnValue({ mutateAsync: mockBeatUpdate, isPending: false });
        mockChapters.mockReturnValue({
            data: [{
                id: 'ch-1',
                story_id: 'story-1',
                chapter_number: 1,
                content: 'Once upon a time...\n\n> Opening move\n\n',
                beats: [{ id: 'b-1', parent_beat_id: null, role: 'user', content: 'Opening move' }],
                image_paths: [],
            }],
            isLoading: false,
        });
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByDisplayValue(/Once upon a time/)).toBeInTheDocument();
        });
        fireEvent.click(screen.getByTitle(/Show story beats/i));
        await waitFor(() => {
            expect(screen.getAllByText(/Opening move/).length).toBeGreaterThan(0);
        });
        fireEvent.click(screen.getByTitle('Edit this beat'));
        const textarea = screen.getByDisplayValue('Opening move');
        fireEvent.change(textarea, { target: { value: 'Revised opening' } });
        fireEvent.click(screen.getByTitle(/Save beat/));
        await waitFor(() => {
            expect(mockBeatUpdate).toHaveBeenCalledWith({
                storyId: 'story-1',
                chapterId: 'ch-1',
                beatId: 'b-1',
                content: 'Revised opening',
                role: 'user',
            });
        });
    });

    it('deletes a beat after confirmation', async () => {
        const mockBeatDelete = vi.fn().mockResolvedValue({});
        mockDeleteStoryBeat.mockReturnValue({ mutateAsync: mockBeatDelete, isPending: false });
        mockChapters.mockReturnValue({
            data: [{
                id: 'ch-1',
                story_id: 'story-1',
                chapter_number: 1,
                content: 'Once upon a time...\n\n> Opening move\n\n',
                beats: [{ id: 'b-1', parent_beat_id: null, role: 'user', content: 'Opening move' }],
                image_paths: [],
            }],
            isLoading: false,
        });
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByDisplayValue(/Once upon a time/)).toBeInTheDocument();
        });
        fireEvent.click(screen.getByTitle(/Show story beats/i));
        await waitFor(() => {
            expect(screen.getAllByText(/Opening move/).length).toBeGreaterThan(0);
        });
        fireEvent.click(screen.getByTitle('Delete this beat and its prose'));
        // confirmationStore is mocked to auto-accept
        await waitFor(() => {
            expect(mockBeatDelete).toHaveBeenCalledWith({
                storyId: 'story-1',
                chapterId: 'ch-1',
                beatId: 'b-1',
            });
        });
    });

    it('opens illustrate modal when Illustrate button is clicked', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByText('Illustrate')).toBeInTheDocument();
        });
        fireEvent.click(screen.getByText('Illustrate'));
        await waitFor(() => {
            expect(screen.getByText('Generate Illustration')).toBeInTheDocument();
        });
    });

    it('illustrates chapter when prompt is submitted in modal', async () => {
        const mockMutate = vi.fn().mockResolvedValue({ job_id: 'img-1' });
        mockIllustrateChapter.mockReturnValue({ mutateAsync: mockMutate, isPending: false });
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByText('Illustrate')).toBeInTheDocument();
        });
        fireEvent.click(screen.getByText('Illustrate'));
        await waitFor(() => {
            expect(screen.getByText('Generate Illustration')).toBeInTheDocument();
        });
        const promptInput = screen.getByPlaceholderText(/moonlit/i);
        fireEvent.change(promptInput, { target: { value: 'A dark castle' } });
        fireEvent.click(screen.getByRole('button', { name: /generate/i }));
        expect(mockMutate).toHaveBeenCalledWith({
            storyId: 'story-1',
            chapterId: 'ch-1',
            image_prompt: 'A dark castle',
        });
    });

    it('opens AI action modal when Summarize button clicked', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByTitle(/summarize the selected text/i)).toBeInTheDocument();
        });
        await waitForEditorHydrated();
        fireEvent.click(screen.getByTitle(/summarize the selected text/i));
        await waitFor(() => {
            expect(screen.getByText('Summarize')).toBeInTheDocument();
        });
    });

    it('submits summarize action with chapter content when confirmed', async () => {
        const mockMutate = vi.fn().mockResolvedValue({ job_id: 'job-1' });
        mockStoryAiAction.mockReturnValue({ mutateAsync: mockMutate, isPending: false });
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByTitle(/summarize the selected text/i)).toBeInTheDocument();
        });
        await waitForEditorHydrated();
        fireEvent.click(screen.getByTitle(/summarize the selected text/i));
        await waitFor(() => {
            expect(screen.getByRole('dialog')).toBeInTheDocument();
        });
        const actionDialog = within(screen.getByRole('dialog'));
        await waitFor(() => {
            expect(actionDialog.getByRole('button', { name: /generate/i })).toBeEnabled();
        });
        fireEvent.click(actionDialog.getByRole('button', { name: /generate/i }));
        await waitFor(() => {
            expect(mockMutate).toHaveBeenCalledWith({
                storyId: 'story-1',
                chapterId: 'ch-1',
                action: 'summarize',
                target_text: 'Once upon a time...',
                directive: '',
            });
        });
        expect(awaitJobText).toHaveBeenCalledWith(expect.objectContaining({ jobId: 'job-1' }));
    }, 15000);

    it('shows toast error when Rewrite clicked without a selection', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByTitle(/rewrite the selected text/i)).toBeInTheDocument();
        });
        fireEvent.click(screen.getByTitle(/rewrite the selected text/i));
        await waitFor(() => {
            expect(toast.error).toHaveBeenCalledWith('Select some text in the editor first');
        });
    });

    it('opens the revision history modal from the action bar', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByTitle(/revision history/i)).toBeInTheDocument();
        });
        fireEvent.click(screen.getByTitle(/revision history/i));
        await waitFor(() => {
            expect(screen.getByTestId('revisions-modal')).toBeInTheDocument();
        });
        expect(screen.queryAllByTestId('revision-row')).toHaveLength(0);
    });

    it('starts a live Roleplay Chat from active chapter and navigates to it', async () => {
        const startChatFn = vi.fn().mockResolvedValue({ chat_id: 'chat-42', title: 'My Story — Chapter 1' });
        mockStartChatFromStory.mockReturnValue({ mutateAsync: startChatFn, isPending: false });

        renderWithProviders(<StorySandbox />);
        await waitFor(() => {
            expect(screen.getByTitle('Roleplay this scene in live Chat')).toBeInTheDocument();
        });

        fireEvent.click(screen.getByTitle('Roleplay this scene in live Chat'));

        await waitFor(() => {
            expect(startChatFn).toHaveBeenCalledWith({
                storyId: 'story-1',
                chapterId: 'ch-1',
            });
        });
    });
});

/**
 * Switching chapters inside the 2s auto-save window used to destroy the pending
 * write outright.
 *
 * The auto-save is a debounce, and its cleanup cancelled the timer. A debounce is
 * *designed* to drop its work when reset — right for a search box, and
 * catastrophic for an editor, because the content lived only inside that closure.
 * On a chapter switch the timer was cancelled, the editor was then overwritten
 * with the new chapter's content, and `isDirtyRef` was reset: the user's last
 * edits to the old chapter were gone with no error, no toast, and no way to
 * recover.
 *
 * The fix holds the payload in a ref so it outlives the timer, and flushes it on
 * the way out. These drive the real editor through the real switch.
 */
describe('StorySandbox auto-save durability', () => {
    const TWO_CHAPTERS = [
        { id: 'ch-1', story_id: 'story-1', chapter_number: 1, content: 'Chapter one text', beats: [], image_paths: [] },
        { id: 'ch-2', story_id: 'story-1', chapter_number: 2, content: 'Chapter two text', beats: [], image_paths: [] },
    ];

    let updateMutateAsync;

    beforeEach(() => {
        vi.clearAllMocks();
        vi.useFakeTimers({ shouldAdvanceTime: true });
        updateMutateAsync = vi.fn().mockResolvedValue({});
        mockStories.mockReturnValue({
            data: [{ id: 'story-1', title: 'My Story', description: '', genre: 'Fantasy' }],
            isLoading: false,
        });
        mockChapters.mockReturnValue({ data: TWO_CHAPTERS, isLoading: false });
        mockLorebooks.mockReturnValue({ data: [], isLoading: false });
        mockCreateStory.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockDeleteStory.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockUpdateStory.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockCreateChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockDeleteChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockUpdateChapter.mockReturnValue({ mutate: vi.fn(), mutateAsync: updateMutateAsync });
        mockContinueChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'j' }) });
        mockBranchChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
        mockAddStoryBeat.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockIllustrateChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'i' }) });
        mockStoryAiAction.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'j' }), isPending: false });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    const editor = () =>
        screen.getAllByRole('textbox').find((el) => el.tagName === 'TEXTAREA');

    it('writes the pending edit when the user switches chapter inside the window', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => expect(editor()?.value).toContain('Chapter one text'), { timeout: 3000 });

        // Type, then immediately switch chapters — well inside the 2s debounce,
        // so the timer would have been cancelled with the text still in it.
        fireEvent.change(editor(), { target: { value: 'Chapter one text EDITED' } });
        fireEvent.click(screen.getAllByText(/Chapter 2/)[0]);

        // The outgoing chapter's edit must be written, not discarded.
        await waitFor(() => {
            expect(updateMutateAsync).toHaveBeenCalledWith(
                expect.objectContaining({ chapterId: 'ch-1', content: 'Chapter one text EDITED' })
            );
        }, { timeout: 3000 });
    });

    it('writes the pending edit on unmount, without waiting for the debounce', async () => {
        const { unmount } = renderWithProviders(<StorySandbox />);
        await waitFor(() => expect(editor()?.value).toContain('Chapter one text'), { timeout: 3000 });

        fireEvent.change(editor(), { target: { value: 'Chapter one text UNMOUNTED' } });
        unmount();

        await waitFor(() => {
            expect(updateMutateAsync).toHaveBeenCalledWith(
                expect.objectContaining({ chapterId: 'ch-1', content: 'Chapter one text UNMOUNTED' })
            );
        }, { timeout: 3000 });
    });

    it('still writes on the debounce when nothing interrupts it', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => expect(editor()?.value).toContain('Chapter one text'), { timeout: 3000 });

        fireEvent.change(editor(), { target: { value: 'Chapter one text DEBOUNCED' } });
        await vi.advanceTimersByTimeAsync(2000);

        await waitFor(() => {
            expect(updateMutateAsync).toHaveBeenCalledWith(
                expect.objectContaining({ chapterId: 'ch-1', content: 'Chapter one text DEBOUNCED' })
            );
        }, { timeout: 3000 });
    });

    it('warns before a tab close while a save is pending', async () => {
        renderWithProviders(<StorySandbox />);
        await waitFor(() => expect(editor()?.value).toContain('Chapter one text'), { timeout: 3000 });

        const event = new Event('beforeunload', { cancelable: true });
        // Nothing pending yet: a dialog here would train people to click through it.
        window.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);

        fireEvent.change(editor(), { target: { value: 'Chapter one text PENDING' } });
        const pending = new Event('beforeunload', { cancelable: true });
        window.dispatchEvent(pending);
        expect(pending.defaultPrevented).toBe(true);
    });

    it('a failed flush is reported and not silently dropped', async () => {
        updateMutateAsync.mockRejectedValueOnce(new Error('network down'));
        renderWithProviders(<StorySandbox />);
        await waitFor(() => expect(editor()?.value).toContain('Chapter one text'), { timeout: 3000 });

        fireEvent.change(editor(), { target: { value: 'Chapter one text WILL FAIL' } });
        fireEvent.click(screen.getAllByText(/Chapter 2/)[0]);

        await waitFor(() => expect(toast.error).toHaveBeenCalled(), { timeout: 3000 });
    });
});

describe('StorySandbox clipboard on an insecure origin', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        vi.useRealTimers();
        mockStories.mockReturnValue({
            data: [{ id: 'story-1', title: 'My Story', description: '', genre: 'Fantasy' }],
            isLoading: false,
        });
        mockChapters.mockReturnValue({
            data: [{ id: 'ch-1', story_id: 'story-1', chapter_number: 1, content: 'Once upon a time...', beats: [], image_paths: [] }],
            isLoading: false,
        });
        mockLorebooks.mockReturnValue({ data: [], isLoading: false });
        mockUpdateChapter.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue({}) });
        mockPublishStory.mockReturnValue({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false });
    });

    /**
     * Publishing a story on a non-secure origin.
     *
     * Measured: `http://100.150.0.4:5174` → `{"secure":false,"clip":false}`,
     * `http://localhost:5174` → both true. On the insecure side,
     * `navigator.clipboard.writeText(...)` throws a SYNCHRONOUS TypeError, so
     * there is no promise for `.then`/`.catch` to attach to and the "Shareable
     * link copied" toast was unreachable — while the "Story published!" toast
     * on the line above had already fired, and the throw escaped `onSuccess`.
     */
    describe('publish story on an insecure origin', () => {
    const publishAndSucceed = () => {
        const mutate = vi.fn();
        mutate.mockImplementation((_vars, { onSuccess }) => onSuccess({ read_url: '/read/story/tok' }));
        mockPublishStory.mockReturnValue({ mutate, mutateAsync: vi.fn(), isPending: false });
        return mutate;
    };

        const clickPublish = () => screen.getByTitle('Publish story to web').click();

        afterEach(() => { vi.unstubAllGlobals(); });

        it('still reports the publish when the clipboard is unavailable', async () => {
            vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });
            publishAndSucceed();

            renderWithProviders(<StorySandbox />);
            clickPublish();

            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Story published!'), { timeout: 3000 });
            // And it says the copy failed, instead of silently claiming it worked.
            const errors = toast.error.mock.calls.map((c) => String(c[0]));
            expect(errors.some((m) => /could not be copied/i.test(m))).toBe(true);
        });

        it('confirms the copy when the clipboard works', async () => {
            const writeText = vi.fn().mockResolvedValue(undefined);
            vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
            publishAndSucceed();

            renderWithProviders(<StorySandbox />);
            clickPublish();

            await waitFor(
                () => expect(toast).toHaveBeenCalledWith(
                    expect.stringContaining('Shareable link copied'),
                    expect.anything()
                ),
                { timeout: 3000 }
            );
            expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/read/story/tok`);
        });

        it('does not report a copy failure when there was no read_url to copy', async () => {
            vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });
            const mutate = vi.fn();
            mutate.mockImplementation((_vars, { onSuccess }) => onSuccess({}));
            mockPublishStory.mockReturnValue({ mutate, mutateAsync: vi.fn(), isPending: false });

            renderWithProviders(<StorySandbox />);
            clickPublish();

            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Story published!'), { timeout: 3000 });
            const errors = toast.error.mock.calls.map((c) => String(c[0]));
            expect(errors.some((m) => /could not be copied/i.test(m))).toBe(false);
        });
    });

    /**
     * Ctrl+Shift+C on the chapter editor.
     *
     * The handler was `navigator.clipboard.writeText(content).then(ok).catch(fail)`,
     * and a bare promise chain does not contain a synchronous TypeError thrown
     * by the dereference itself. It also runs from a `keydown` listener, where
     * the throw had nowhere to surface: on a LAN address the shortcut did
     * nothing at all, with no message.
     */
    describe('Ctrl+Shift+C chapter copy on an insecure origin', () => {
        afterEach(() => { vi.unstubAllGlobals(); });

        it('reports the outcome instead of throwing out of the keydown listener', async () => {
            vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });

            renderWithProviders(<StorySandbox />);
            await waitForEditorHydrated();

            // Must not throw: an exception here would escape into the document
            // and the user would see nothing.
            expect(() => {
                window.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'c', ctrlKey: true, shiftKey: true, bubbles: true,
                }));
            }).not.toThrow();

            await waitFor(
                () => {
                    const messages = [
                        ...toast.success.mock.calls.map((c) => String(c[0])),
                        ...toast.error.mock.calls.map((c) => String(c[0])),
                    ];
                    expect(messages.some((m) => /copied to clipboard|Failed to copy/i.test(m))).toBe(true);
                },
                { timeout: 3000 }
            );
        });

        it('confirms the copy when the clipboard works', async () => {
            const writeText = vi.fn().mockResolvedValue(undefined);
            vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });

            renderWithProviders(<StorySandbox />);
            await waitForEditorHydrated();

            window.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'c', ctrlKey: true, shiftKey: true, bubbles: true,
            }));

            await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Chapter content copied to clipboard'), { timeout: 3000 });
            expect(writeText).toHaveBeenCalledWith('Once upon a time...');
        });
    });
});
