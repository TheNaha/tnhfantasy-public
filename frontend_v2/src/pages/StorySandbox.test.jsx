import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StorySandbox from './StorySandbox';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

Element.prototype.scrollIntoView = vi.fn();

const mockActiveStoryId = vi.hoisted(() => vi.fn(() => 'story-1'));
const mockActiveChapterId = vi.hoisted(() => vi.fn(() => 'ch-1'));
const mockSetActiveStory = vi.hoisted(() => vi.fn());
const mockSetActiveChapter = vi.hoisted(() => vi.fn());

vi.mock('../store/worldVaultStore', () => ({
    useWorldVaultStore: (sel) =>
        sel({
            activeStoryId: mockActiveStoryId(),
            activeChapterId: mockActiveChapterId(),
            setActiveStory: mockSetActiveStory,
            setActiveChapter: mockSetActiveChapter,
            contextBuilder: { selectedLorebooks: [], systemPromptOverride: null, maxContextTokens: 4096 },
            selectedLorebooks: [],
            toggleLorebook: vi.fn(),
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
const mockAddStoryBeat = vi.hoisted(() => vi.fn());
const mockIllustrateChapter = vi.hoisted(() => vi.fn());

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
    useContinueChapter: (...a) => mockContinueChapter(...a),
    useAddStoryBeat: (...a) => mockAddStoryBeat(...a),
    useIllustrateChapter: (...a) => mockIllustrateChapter(...a),
    useCharacters: () => ({ data: [] }),
}));

vi.mock('../api/websocket', () => ({
    useWebSocket: () => ({ subscribe: vi.fn(() => vi.fn()), unsubscribe: vi.fn() }),
    EventTypes: { JOB_PROGRESS: 'job.progress', JOB_COMPLETED: 'job.completed', JOB_FAILED: 'job.failed' },
}));

vi.mock('../api', () => ({
    api: { put: vi.fn().mockResolvedValue({}) },
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
    },
    AnimatePresence: ({ children }) => <>{children}</>,
}));

function renderWithProviders(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>{ui}</MemoryRouter>
        </QueryClientProvider>
    );
}

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
        mockUpdateChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockContinueChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'job-1' }) });
        mockAddStoryBeat.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockIllustrateChapter.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ job_id: 'img-1' }) });
    });

    it('renders the stories sidebar', () => {
        renderWithProviders(<StorySandbox />);
        expect(screen.getByText('Stories')).toBeInTheDocument();
    });

    it('displays story list in sidebar', () => {
        renderWithProviders(<StorySandbox />);
        expect(screen.getByText('My Story')).toBeInTheDocument();
    });

    it('displays chapter list', () => {
        renderWithProviders(<StorySandbox />);
        expect(screen.getByText(/Chapter 1/)).toBeInTheDocument();
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
});
