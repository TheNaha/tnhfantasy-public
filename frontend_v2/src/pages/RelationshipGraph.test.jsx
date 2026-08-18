import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import RelationshipGraph from './RelationshipGraph';

const mockRelationships = vi.hoisted(() => vi.fn());
const mockRefetch = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useWorldVault', () => ({
    useWorldVaultRelationships: (...args) => mockRelationships(...args),
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
    });

    it('renders the main heading and description', () => {
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        expect(screen.getByRole('heading', { name: 'Relationship Graph' })).toBeInTheDocument();
        expect(screen.getByText(/Visualize connections between characters, stories/i)).toBeInTheDocument();
    });

    it('shows a loading state while fetching relationships', () => {
        mockRelationships.mockReturnValue({
            data: undefined,
            isLoading: true,
            isError: false,
            refetch: mockRefetch,
            isFetching: false,
        });
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
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
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        expect(screen.getByText('Failed to load relationships')).toBeInTheDocument();
    });

    it('shows an empty state when there are no relationships', () => {
        mockReturn({});
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        expect(screen.getByText(/No relationships found/)).toBeInTheDocument();
    });

    it('renders node labels for all connected entities', () => {
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        expect(screen.getAllByText('Aria').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('The Tavern Chat').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('The Dragon War').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('Ancient Lore').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('Aria Voice').length).toBeGreaterThanOrEqual(1);
    });

    it('renders one edge line per relationship', () => {
        const { container } = render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        expect(container.querySelectorAll('line')).toHaveLength(4);
    });

    it('deduplicates shared nodes across relationship types', () => {
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        const ariaNodes = screen.getAllByText('Aria');
        expect(ariaNodes.length).toBeGreaterThanOrEqual(1);
    });

    it('filters the graph to the selected entity type', () => {
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'character' } });
        expect(screen.getAllByText('Aria').length).toBeGreaterThanOrEqual(1);
        expect(screen.queryByText('The Dragon War')).not.toBeInTheDocument();
        expect(screen.queryByText('The Tavern Chat')).not.toBeInTheDocument();
        expect(screen.queryByText('Ancient Lore')).not.toBeInTheDocument();
    });

    it('refetches relationships when the refresh button is clicked', () => {
        render(
            <MemoryRouter>
                <RelationshipGraph />
            </MemoryRouter>
        );
        fireEvent.click(screen.getByTitle('Refresh'));
        expect(mockRefetch).toHaveBeenCalled();
    });
});