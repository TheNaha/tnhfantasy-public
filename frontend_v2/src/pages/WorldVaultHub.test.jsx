import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WorldVaultHub from './WorldVaultHub';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate };
});

const mockSearch = vi.hoisted(() => vi.fn());
const mockDashboard = vi.hoisted(() => vi.fn());
const mockEntity = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useWorldVaultSearch', () => ({
    useWorldVaultSearch: (...args) => mockSearch(...args),
    useWorldVaultDashboard: (...args) => mockDashboard(...args),
    useWorldVaultEntity: (...args) => mockEntity(...args),
    // Mirrors the real module so the page under test reads the same bounds.
    WORLD_VAULT_SEARCH_MIN_LENGTH: 2,
    WORLD_VAULT_MENTION_TYPES: ['character', 'lorebook', 'location'],
}));

vi.mock('../hooks/useDebounce', () => ({
    useDebounce: (value) => value,
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
    },
    AnimatePresence: ({ children }) => <>{children}</>,
}));

const dashboardData = {
    recent: {
        characters: [{ id: 'char-1', name: 'Aria the Mage', created_at: '2026-08-01T00:00:00Z' }],
        chats: [{ id: 'chat-1', name: 'The Tavern Chat', created_at: '2026-08-01T00:00:00Z' }],
        stories: [],
    },
    counts: { characters: 3, chats: 5, stories: 2 },
};

function renderWithProviders(ui, initialEntries = ['/']) {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
        </QueryClientProvider>
    );
}

describe('WorldVaultHub page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockDashboard.mockReturnValue({ data: dashboardData, isLoading: false });
        mockSearch.mockReturnValue({ data: [], isLoading: false });
        mockEntity.mockReturnValue({ data: undefined, isLoading: false, isError: false });
    });

    it('renders the main heading, description, search input, and type filter', () => {
        renderWithProviders(<WorldVaultHub />);
        expect(screen.getByRole('heading', { name: 'World Vault' })).toBeInTheDocument();
        expect(screen.getByText(/Central hub for all your fantasy entities/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Search across all entities...')).toBeInTheDocument();
        expect(screen.getByRole('combobox')).toBeInTheDocument();
    });

    it('renders entity counts from the dashboard', () => {
        renderWithProviders(<WorldVaultHub />);
        expect(screen.getByText('Entity Counts')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
        expect(screen.getByText('5')).toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('renders recent entities from the dashboard', () => {
        renderWithProviders(<WorldVaultHub />);
        expect(screen.getByText('Aria the Mage')).toBeInTheDocument();
        expect(screen.getByText('The Tavern Chat')).toBeInTheDocument();
    });

    it('shows loading state while fetching', () => {
        mockDashboard.mockReturnValue({ data: undefined, isLoading: true });
        mockSearch.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<WorldVaultHub />);
        expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('shows empty state when there are no entities', () => {
        mockDashboard.mockReturnValue({ data: { recent: {}, counts: {} }, isLoading: false });
        renderWithProviders(<WorldVaultHub />);
        expect(screen.getByText('No entities yet')).toBeInTheDocument();
    });

    it('displays search results once a query is typed', () => {
        mockDashboard.mockReturnValue({ data: { recent: {}, counts: {} }, isLoading: false });
        mockSearch.mockReturnValue({
            data: {
                query: 'aria',
                total: 1,
                results: [{ id: 'c-9', type: 'character', title: 'Aria Found', subtitle: 'found via search' }],
            },
            isLoading: false,
        });
        renderWithProviders(<WorldVaultHub />);
        fireEvent.change(screen.getByPlaceholderText('Search across all entities...'), {
            target: { value: 'aria' },
        });
        expect(screen.getByText('Aria Found')).toBeInTheDocument();
        expect(screen.getByText('found via search')).toBeInTheDocument();
    });

    it('shows a no-results message when the search finds nothing', () => {
        mockDashboard.mockReturnValue({ data: { recent: {}, counts: {} }, isLoading: false });
        mockSearch.mockReturnValue({ data: { query: 'zzz', results: [], total: 0 }, isLoading: false });
        renderWithProviders(<WorldVaultHub />);
        fireEvent.change(screen.getByPlaceholderText('Search across all entities...'), {
            target: { value: 'zzz' },
        });
        expect(screen.getByText('No results found')).toBeInTheDocument();
    });

    it('navigates to the chat when a chat entity is clicked', () => {
        renderWithProviders(<WorldVaultHub />);
        fireEvent.click(screen.getByRole('button', { name: /The Tavern Chat/ }));
        expect(mockNavigate).toHaveBeenCalledWith('/chat/chat-1');
    });

    it('opens an entity when Enter is pressed on a card', () => {
        renderWithProviders(<WorldVaultHub />);
        fireEvent.keyDown(screen.getByRole('button', { name: /The Tavern Chat/ }), { key: 'Enter' });
        expect(mockNavigate).toHaveBeenCalledWith('/chat/chat-1');
    });

    it('passes the selected entity type as a filter to the search hook', () => {
        mockDashboard.mockReturnValue({ data: { recent: {}, counts: {} }, isLoading: false });
        mockSearch.mockReturnValue({ data: { query: 'aria', results: [], total: 0 }, isLoading: false });
        renderWithProviders(<WorldVaultHub />);
        fireEvent.change(screen.getByPlaceholderText('Search across all entities...'), {
            target: { value: 'aria' },
        });
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'character' } });
        expect(mockSearch).toHaveBeenLastCalledWith('aria', 'character');
    });

    it('offers a location filter, which the search endpoint can return', () => {
        renderWithProviders(<WorldVaultHub />);
        expect(screen.getByRole('option', { name: 'Location' })).toBeInTheDocument();
    });

    it('does not search on a single character and says why', () => {
        renderWithProviders(<WorldVaultHub />);
        fireEvent.change(screen.getByPlaceholderText('Search across all entities...'), {
            target: { value: 'a' },
        });
        expect(screen.getByText(/type at least 2 characters to search/i)).toBeInTheDocument();
        // The hub keeps the recents visible instead of showing an empty result.
        expect(screen.getByText('Aria the Mage')).toBeInTheDocument();
    });

    it('resolves a story @mention deep link and opens the entity it names', () => {
        mockEntity.mockReturnValue({
            data: { id: 'char-9', name: 'Lyra Vale', description: 'A silver-tongued smuggler' },
            isLoading: false,
            isError: false,
        });
        renderWithProviders(<WorldVaultHub />, ['/world-vault?character=char-9']);

        expect(mockEntity).toHaveBeenCalledWith('character', 'char-9');
        expect(screen.getByRole('heading', { name: 'Linked from your story' })).toBeInTheDocument();
        expect(screen.getByText('Lyra Vale')).toBeInTheDocument();
        // The type filter follows the mention so follow-up searches stay scoped.
        expect(screen.getByRole('combobox')).toHaveValue('character');

        fireEvent.click(screen.getByText('Lyra Vale'));
        expect(mockNavigate).toHaveBeenCalledWith('/characters#char-char-9');
    });

    it('falls back to the entity library when a mention id cannot be loaded', () => {
        mockEntity.mockReturnValue({ data: undefined, isLoading: false, isError: true });
        renderWithProviders(<WorldVaultHub />, ['/world-vault?lorebook=book-3']);

        expect(mockEntity).toHaveBeenCalledWith('lorebook', 'book-3');
        fireEvent.click(screen.getByText(/opening its library instead/i));
        expect(mockNavigate).toHaveBeenCalledWith('/lorebooks');
    });

    it('has no mention section when the URL carries no mention parameter', () => {
        renderWithProviders(<WorldVaultHub />);
        expect(mockEntity).not.toHaveBeenCalled();
        expect(screen.queryByRole('heading', { name: 'Linked from your story' })).not.toBeInTheDocument();
    });

    it('does not self-navigate when a result type has no page', () => {
        mockDashboard.mockReturnValue({ data: { recent: {}, counts: {} }, isLoading: false });
        mockSearch.mockReturnValue({
            data: { query: 'mystery', results: [{ id: 'x-1', type: 'branch', title: 'Unroutable' }] },
            isLoading: false,
        });
        renderWithProviders(<WorldVaultHub />);
        fireEvent.change(screen.getByPlaceholderText('Search across all entities...'), {
            target: { value: 'mystery' },
        });
        fireEvent.click(screen.getByText('Unroutable'));
        expect(mockNavigate).not.toHaveBeenCalledWith('/world-vault');
    });
});
