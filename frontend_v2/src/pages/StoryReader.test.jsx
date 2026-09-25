import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import StoryReader from './StoryReader';

const mockNavigate = vi.hoisted(() => vi.fn());
const mockParams = vi.hoisted(() => vi.fn(() => ({ token: 'tok123' })));
const mockApiGet = vi.hoisted(() => vi.fn());
const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate, useParams: mockParams };
});

vi.mock('../api', () => ({
    api: { get: (...args) => mockApiGet(...args) },
}));

vi.mock('react-hot-toast', () => ({ default: mockToast }));

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
    },
    AnimatePresence: ({ children }) => <>{children}</>,
}));

const storyData = {
    story: {
        title: 'The Dragon of Ashvale',
        description: 'A tale of fire and ruin',
        memory: 'Keep a secret close.',
    },
    characters: [{ name: 'Elara' }, { name: 'Kael' }],
    chapters: [
        {
            chapter_number: 1,
            title: 'The Beginning',
            content: 'Once upon a time **a dragon** slept.\nThen it woke.',
            image_paths: ['/static/dragon.png', 'cave.png'],
        },
    ],
};

function renderPage() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={['/read/tok123']}>
                <StoryReader />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('StoryReader page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApiGet.mockImplementation(async (url) => {
            if (url.includes('/export')) return { content: '# The Dragon of Ashvale' };
            return storyData;
        });
        Object.defineProperty(navigator, 'clipboard', {
            value: { writeText: vi.fn().mockResolvedValue(undefined) },
            configurable: true,
        });
        vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:story');
        vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    });

    it('shows the loading state while fetching the story', () => {
        mockApiGet.mockReturnValue(new Promise(() => {}));
        renderPage();
        expect(screen.getByText('Loading story...')).toBeInTheDocument();
    });

    it('renders the story title and description', async () => {
        renderPage();
        expect(await screen.findByRole('heading', { name: 'The Dragon of Ashvale' })).toBeInTheDocument();
        expect(screen.getByText('A tale of fire and ruin')).toBeInTheDocument();
    });

    it('renders the author note from story memory', async () => {
        renderPage();
        await screen.findByText('The Dragon of Ashvale');
        expect(screen.getByText("Author's Note")).toBeInTheDocument();
        expect(screen.getByText('Keep a secret close.')).toBeInTheDocument();
    });

    it('renders character chips', async () => {
        renderPage();
        await screen.findByText('The Dragon of Ashvale');
        expect(screen.getByText('Elara')).toBeInTheDocument();
        expect(screen.getByText('Kael')).toBeInTheDocument();
    });

    it('renders chapter headings', async () => {
        renderPage();
        await screen.findByText('The Dragon of Ashvale');
        expect(screen.getByRole('heading', { name: 'Chapter 1: The Beginning' })).toBeInTheDocument();
    });

    it('converts chapter markdown to bold markup', async () => {
        const { container } = renderPage();
        await screen.findByText('The Dragon of Ashvale');
        const prose = container.querySelector('.prose');
        expect(prose.textContent).toContain('Once upon a time');
        expect(prose.querySelector('strong').textContent).toBe('a dragon');
    });

    it('renders chapter illustrations with normalized asset paths', async () => {
        renderPage();
        await screen.findByText('The Dragon of Ashvale');
        const imgs = screen.getAllByAltText('Chapter 1 illustration');
        expect(imgs).toHaveLength(2);
        expect(imgs[0]).toHaveAttribute('src', '/static/dragon.png');
        expect(imgs[1]).toHaveAttribute('src', '/api/view/output/cave.png');
    });

    it('copies the share link and toasts success', async () => {
        renderPage();
        await screen.findByText('The Dragon of Ashvale');
        fireEvent.click(screen.getByTitle('Share link'));
        await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(window.location.href));
        expect(mockToast.success).toHaveBeenCalledWith('Link copied!');
    });

    it('exports the story as markdown', async () => {
        renderPage();
        await screen.findByText('The Dragon of Ashvale');
        fireEvent.click(screen.getByTitle('Export as Markdown'));
        await waitFor(() =>
            expect(mockApiGet).toHaveBeenCalledWith(
                '/api/v2/stories/published/tok123/export?format=md',
                { timeout: 180000 }
            )
        );
        expect(URL.createObjectURL).toHaveBeenCalled();
        expect(mockToast.success).toHaveBeenCalledWith('Exported as MD');
    });

    it('shows an error toast and navigates home when the story is missing', async () => {
        mockApiGet.mockRejectedValue(new Error('not found'));
        renderPage();
        await waitFor(() => expect(mockToast.error).toHaveBeenCalledWith('Story not found or no longer available'));
        expect(mockNavigate).toHaveBeenCalledWith('/');
    });
});