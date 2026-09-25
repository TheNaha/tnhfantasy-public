import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import EntityContextInspector from './EntityContextInspector';

const useLorebookEntriesMock = vi.hoisted(() => vi.fn());

vi.mock('../../hooks/useLorebooks', () => ({
    useLorebookEntries: (id) => useLorebookEntriesMock(id),
}));

const characters = [
    { id: 'char-1', name: 'Lyra Vane', description: 'A cartographer', avatar_path: 'a.png' },
    { id: 'char-2', name: 'Orrin', description: 'A smuggler' },
];
const lorebooks = [{ id: 'lb-1', name: 'Ashfall Codex' }, { id: 'lb-2', name: 'Riverlands' }];
const locations = [{ id: 'loc-1', name: 'Greyharbor', atmosphere: 'Salt and tar' }];
const entries = [
    { id: 'e-1', keys: [], content: 'The tide never returns what it takes.' },
    { id: 'e-2', keys: ['Greyharbor'], content: 'Greyharbor lies east of the reef.' },
    { id: 'e-3', keys: ['dragons'], content: 'No dragon has crossed the mountains.' },
];

function renderInspector(props = {}) {
    const navigate = vi.fn();
    const utils = render(
        <MemoryRouter>
            <EntityContextInspector
                characters={characters}
                characterIds={['char-1']}
                lorebooks={lorebooks}
                lorebookIds={['lb-1']}
                locations={locations}
                locationIds={['loc-1']}
                contextText="The crew sailed toward Greyharbor at dusk."
                onNavigate={navigate}
                {...props}
            />
        </MemoryRouter>
    );
    return { ...utils, navigate };
}

const openInspector = () => fireEvent.click(screen.getByRole('button', { name: /Context Inspector/i }));

describe('EntityContextInspector', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        useLorebookEntriesMock.mockReturnValue({ data: entries, isLoading: false, isError: false });
    });

    it('is collapsed by default and summarizes linked entities', () => {
        renderInspector();

        const toggle = screen.getByRole('button', { name: /Context Inspector/i });
        expect(toggle).toHaveAttribute('aria-expanded', 'false');
        expect(screen.queryByTestId('inspector-characters')).not.toBeInTheDocument();
        expect(screen.getByText('1 linked · 1 location · 1 lorebook')).toBeInTheDocument();
    });

    it('opens on click and lists linked characters and locations', () => {
        renderInspector();
        openInspector();

        expect(screen.getByRole('button', { name: /Context Inspector/i })).toHaveAttribute('aria-expanded', 'true');
        expect(screen.getByText('Lyra Vane')).toBeInTheDocument();
        expect(screen.getByText('A cartographer')).toBeInTheDocument();
        expect(screen.getByText('Greyharbor')).toBeInTheDocument();
        expect(screen.getByText('Salt and tar')).toBeInTheDocument();
    });

    it('excludes entities that are not linked', () => {
        renderInspector();
        openInspector();

        expect(screen.queryByText('Orrin')).not.toBeInTheDocument();
        expect(screen.queryByText('Riverlands')).not.toBeInTheDocument();
    });

    it('shows the empty hint when nothing is linked', () => {
        renderInspector({ characterIds: [], lorebookIds: [], locationIds: [] });
        expect(screen.getByText('Nothing linked yet')).toBeInTheDocument();

        openInspector();
        expect(screen.getByText(/Link characters, a location, or a lorebook/)).toBeInTheDocument();
    });

    it('does not fetch lorebook entries until a lorebook row is expanded', () => {
        renderInspector();
        openInspector();

        expect(useLorebookEntriesMock).not.toHaveBeenCalled();
        expect(screen.getByText('Ashfall Codex')).toBeInTheDocument();
    });

    it('surfaces triggered and dormant entries on demand', async () => {
        renderInspector();
        openInspector();

        fireEvent.click(screen.getByRole('button', { name: /Ashfall Codex/ }));

        await waitFor(() => expect(useLorebookEntriesMock).toHaveBeenCalledWith('lb-1'));
        expect(await screen.findByText('The tide never returns what it takes.')).toBeInTheDocument();
        expect(screen.getByText('Greyharbor lies east of the reef.')).toBeInTheDocument();
        expect(screen.getByText('2 of 3 entries would be injected now')).toBeInTheDocument();
        expect(screen.getByText('1 dormant entry — keys not present in context')).toBeInTheDocument();
        expect(screen.getByText('always')).toBeInTheDocument();
        expect(screen.getByText('triggered')).toBeInTheDocument();
    });

    it('reports a load failure without crashing', async () => {
        useLorebookEntriesMock.mockReturnValue({ data: undefined, isLoading: false, isError: true });
        renderInspector();
        openInspector();

        fireEvent.click(screen.getByRole('button', { name: /Ashfall Codex/ }));

        expect(await screen.findByText('Could not load entries.')).toBeInTheDocument();
    });

    it('shows a loading state while entries are fetched', () => {
        useLorebookEntriesMock.mockReturnValue({ data: undefined, isLoading: true, isError: false });
        renderInspector();
        openInspector();

        fireEvent.click(screen.getByRole('button', { name: /Ashfall Codex/ }));

        expect(screen.getByText(/Loading entries/)).toBeInTheDocument();
    });

    it('navigates through the quick links', () => {
        const { navigate } = renderInspector();
        openInspector();

        fireEvent.click(screen.getByRole('button', { name: 'Lorebooks' }));
        expect(navigate).toHaveBeenCalledWith('/lorebooks');

        fireEvent.click(screen.getByRole('button', { name: 'Locations' }));
        expect(navigate).toHaveBeenCalledWith('/locations');
    });

    it('renders extra quick links and forwards their handlers', () => {
        const onEditCharacter = vi.fn();
        const { navigate } = renderInspector({
            extraLinks: [{ to: '/world-graph', label: 'Relationships' }],
            onEditCharacter,
        });
        openInspector();

        fireEvent.click(screen.getByRole('button', { name: 'Relationships' }));
        expect(navigate).toHaveBeenCalledWith('/world-graph');

        fireEvent.click(screen.getByTitle('Edit Lyra Vane'));
        expect(onEditCharacter).toHaveBeenCalledWith(characters[0]);
    });

    it('offers edit only for the primary character when one is marked', () => {
        renderInspector({
            characterIds: ['char-1', 'char-2'],
            primaryCharacterId: 'char-1',
            onEditCharacter: vi.fn(),
        });
        openInspector();

        expect(screen.getByTitle('Edit Lyra Vane')).toBeInTheDocument();
        expect(screen.queryByTitle('Edit Orrin')).not.toBeInTheDocument();
    });

    it('surfaces a free-text location when no Location is linked', () => {        renderInspector({ locationIds: [], freeformLocation: 'The Saltmarsh Inn' });
        openInspector();

        expect(screen.getByTestId('inspector-locations')).toBeInTheDocument();
        expect(screen.getByText('The Saltmarsh Inn')).toBeInTheDocument();
    });
});
