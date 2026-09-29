import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import RelationshipGraph from './RelationshipGraph';

const mockRelationships = vi.hoisted(() => vi.fn());
const mockRefetch = vi.hoisted(() => vi.fn());
const mockGraphLayout = vi.hoisted(() => vi.fn());
const mockSaveLayout = vi.hoisted(() => vi.fn());
const mockDeleteLayout = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useWorldVaultSearch', () => ({
    useWorldVaultRelationships: (...args) => mockRelationships(...args),
    useGraphLayout: (...args) => mockGraphLayout(...args),
    useSaveGraphLayout: () => ({ mutate: mockSaveLayout, isPending: false }),
    useDeleteGraphLayout: () => ({ mutate: mockDeleteLayout, isPending: false }),
}));

const graphData = {
    character_chats: [['char-1', 'Aria', 'chat-1', 'The Tavern Chat']],
    character_stories: [
        { character_id: 'char-1', character_name: 'Aria', story_id: 'story-1', story_title: 'The Dragon War' },
    ],
    story_lorebooks: [
        { story_id: 'story-1', story_title: 'The Dragon War', lorebook_id: 'lore-1', lorebook_name: 'Ancient Lore' },
    ],
    character_voices: [['voice-1', 'Aria Voice', 'char-1', 'Aria']],
};

function createWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    function Wrapper({ children }) {
        return (
            <QueryClientProvider client={queryClient}>
                <MemoryRouter>
                    {children}
                </MemoryRouter>
            </QueryClientProvider>
        );
    }
    return Wrapper;
}

function mockReturn(value) {
    mockRelationships.mockReturnValue({
        data: value,
        isLoading: false,
        isError: false,
        refetch: mockRefetch,
        isFetching: false,
    });
}

describe('RelationshipGraph page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockReturn(graphData);
        mockGraphLayout.mockReturnValue({ data: null, isLoading: false });
    });

    it('renders the main heading and description', () => {
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        expect(screen.getByRole('heading', { name: 'Relationship Graph' })).toBeInTheDocument();
        expect(screen.getByText(/Drag nodes to reposition/i)).toBeInTheDocument();
    });

    it('shows a loading state while fetching relationships', () => {
        mockRelationships.mockReturnValue({
            data: undefined,
            isLoading: true,
            isError: false,
            refetch: mockRefetch,
            isFetching: false,
        });
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        expect(screen.getByText('Loading relationships...')).toBeInTheDocument();
    });

    it('shows an error state when loading fails', () => {
        mockRelationships.mockReturnValue({
            data: undefined,
            isLoading: false,
            isError: true,
            refetch: mockRefetch,
            isFetching: false,
        });
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        expect(screen.getByText('Failed to load relationships')).toBeInTheDocument();
    });

    it('shows an empty state when there are no relationships', () => {
        mockReturn({});
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        expect(screen.getByText(/No relationships found/)).toBeInTheDocument();
    });

    it('renders node labels for all connected entities', () => {
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        expect(screen.getAllByText('Aria').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('The Tavern Chat').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('The Dragon War').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('Ancient Lore').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('Aria Voice').length).toBeGreaterThanOrEqual(1);
    });

    it('renders one edge line per relationship', () => {
        const { container } = render(<RelationshipGraph />, { wrapper: createWrapper() });
        expect(container.querySelectorAll('line')).toHaveLength(4);
    });

    it('deduplicates shared nodes across relationship types', () => {
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        const ariaNodes = screen.getAllByText('Aria');
        expect(ariaNodes.length).toBeGreaterThanOrEqual(1);
    });

    it('filters the graph to the selected entity type', () => {
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'character' } });
        expect(screen.getAllByText('Aria').length).toBeGreaterThanOrEqual(1);
        expect(screen.queryByText('The Dragon War')).not.toBeInTheDocument();
        expect(screen.queryByText('The Tavern Chat')).not.toBeInTheDocument();
        expect(screen.queryByText('Ancient Lore')).not.toBeInTheDocument();
    });

    it('refetches relationships when the refresh button is clicked', () => {
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        const buttons = screen.getAllByRole('button');
        const refreshBtn = buttons.find(b => b.title === 'Refresh');
        fireEvent.click(refreshBtn);
        expect(mockRefetch).toHaveBeenCalled();
    });

    it('renders a save layout button', () => {
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        expect(screen.getByText('Saved')).toBeInTheDocument();
    });

    it('renders a reset layout button', () => {
        render(<RelationshipGraph />, { wrapper: createWrapper() });
        const buttons = screen.getAllByRole('button');
        const resetBtn = buttons.find(b => b.title === 'Reset layout');
        expect(resetBtn).toBeInTheDocument();
    });
});
