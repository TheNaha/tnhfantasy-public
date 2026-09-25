import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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

vi.mock('../hooks/useWorldVault', () => ({
    useStories: (...a) => mockStories(...a),
    useStory: () => ({ data: null }),
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
    useDeleteStoryBeat: (...a) => mockDeleteStoryBeat(...a),
    useChapterRevisions: () => ({ data: [], isLoading: false }),
    useCreateChapterRevision: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
    useRestoreChapterRevision: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
    useCharacters: () => ({ data: [] }),
    useLocations: () => ({ data: [] }),
    useLLMAvailableModels: () => ({ data: [] }),
    useLLMDefaultProvider: () => ({ data: null }),
    useStoryImages: () => ({ data: [] }),
    useUpdateCharacter: () => ({ mutateAsync: vi.fn() }),
    useParseStory: () => ({ mutateAsync: vi.fn() }),
    useExportStoryFormatted: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useExportPublishedStory: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    usePublishStory: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useUnpublishStory: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
    useNarrateChapter: () => ({ mutate: vi.fn(), mutateAsync: vi.fn() }),
}));

vi.mock('../api/websocket', () => ({
    useWebSocket: () => ({ subscribe: vi.fn(() => vi.fn()), unsubscribe: vi.fn() }),
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

vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn() },
    toast: vi.fn(),
}));

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
        }, { timeout: 3000 });
    }, 5000);

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
        fireEvent.click(screen.getByRole('button', { name: /continue/i }));
        expect(mockMutate).toHaveBeenCalledWith({
            storyId: 'story-1',
            chapterId: 'ch-1',
            prompt: '',
        });
    });

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
    });

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
});
