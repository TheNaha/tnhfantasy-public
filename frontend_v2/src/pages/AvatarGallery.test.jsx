import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AvatarGallery from './AvatarGallery';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

const mockNavigate = vi.hoisted(() => vi.fn());
const mockCharacters = vi.hoisted(() => vi.fn());
const mockCharacterCollection = vi.hoisted(() => vi.fn());

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../hooks/useWorldVault', () => ({
    useCharacters: (...args) => mockCharacters(...args),
    useCharacterCollection: (...args) => mockCharacterCollection(...args),
    getAvatarUrl: (id) => (id ? `/api/v2/characters/${id}/avatar` : null),
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

const characters = [
    {
        id: 'c1',
        name: 'Elara Moonwhisper',
        description: 'Elven sorceress',
        personality: 'Curious and bold',
        visual_tags: ['elf', 'arcane', 'blue hair'],
        has_avatar: true,
    },
    {
        id: 'c2',
        name: 'Grimjaw',
        description: 'Orc warlord',
        visual_tags: ['orc'],
        has_avatar: false,
    },
];

function renderPage() {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>
                <AvatarGallery />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('AvatarGallery page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockCharacters.mockReturnValue({ data: characters, isLoading: false });
        mockCharacterCollection.mockReturnValue({
            data: { image_count: 2, images: ['scene_a.png', 'scene_b.png'] },
        });
    });

    it('renders the main heading and subtitle', () => {
        renderPage();
        expect(screen.getByRole('heading', { name: 'Character Avatar Gallery' })).toBeInTheDocument();
        expect(screen.getByText('Browse character avatars, scenes, and expression sheets')).toBeInTheDocument();
    });

    it('renders character cards with names and descriptions', () => {
        renderPage();
        expect(screen.getByText('Elara Moonwhisper')).toBeInTheDocument();
        expect(screen.getByText('Grimjaw')).toBeInTheDocument();
        expect(screen.getByText('Elven sorceress')).toBeInTheDocument();
        expect(screen.getByText('Orc warlord')).toBeInTheDocument();
        expect(screen.getByText('elf')).toBeInTheDocument();
        expect(screen.getByText('orc')).toBeInTheDocument();
    });

    it('renders avatar images for characters with avatars', () => {
        renderPage();
        const avatar = screen.getByAltText('Elara Moonwhisper');
        expect(avatar).toHaveAttribute('src', '/api/v2/characters/c1/avatar');
        expect(screen.queryByAltText('Grimjaw')).not.toBeInTheDocument();
    });

    it('shows scene counts from character collections', () => {
        renderPage();
        expect(screen.getAllByText('Scenes (2)')).toHaveLength(2);
    });

    it('shows loading state while fetching characters', () => {
        mockCharacters.mockReturnValue({ data: [], isLoading: true });
        renderPage();
        expect(screen.getByText('Loading characters...')).toBeInTheDocument();
    });

    it('shows empty state when there are no characters', () => {
        mockCharacters.mockReturnValue({ data: [], isLoading: false });
        renderPage();
        expect(screen.getByText('No characters found')).toBeInTheDocument();
        expect(screen.getByText('Create some characters first to see them here.')).toBeInTheDocument();
    });

    it('filters characters by search query across name, description, and tags', () => {
        renderPage();
        const search = screen.getByPlaceholderText('Search characters...');
        fireEvent.change(search, { target: { value: 'elf' } });
        expect(screen.getByText('Elara Moonwhisper')).toBeInTheDocument();
        expect(screen.queryByText('Grimjaw')).not.toBeInTheDocument();
        fireEvent.change(search, { target: { value: 'warlord' } });
        expect(screen.getByText('Grimjaw')).toBeInTheDocument();
        expect(screen.queryByText('Elara Moonwhisper')).not.toBeInTheDocument();
    });

    it('navigates to chat with the character id when Chat is clicked', () => {
        renderPage();
        fireEvent.click(screen.getAllByText('Chat')[0]);
        expect(mockNavigate).toHaveBeenCalledWith('/chat', { state: { characterId: 'c1' } });
    });

    it('switches to grid view which shows image count badges and hides card actions', () => {
        renderPage();
        expect(screen.getAllByText('Chat')).toHaveLength(2);
        fireEvent.click(screen.getByTitle('Grid view'));
        expect(screen.queryAllByText('Chat')).toHaveLength(0);
        expect(screen.queryByText('Scenes (2)')).not.toBeInTheDocument();
        expect(screen.getAllByText('2')).toHaveLength(2);
        fireEvent.click(screen.getByTitle('Card view'));
        expect(screen.getAllByText('Chat')).toHaveLength(2);
    });
});