/**
 * The Worlds page and its hook, against the REAL modules.
 *
 * This file previously existed as `Campaigns.test.jsx` and did
 * `vi.mock('../hooks/useCampaigns')`. That mock is precisely why the suite was
 * green against a 404: the page under test imported a hook that pointed at
 * `/api/v2/campaigns`, a route `a338abc0` had deleted, and the test supplied the
 * data the hook would have fetched, so nothing could fail. Audit P1-18 of
 * 2026-09-29b found the defect, and the 2026-09-29 audit's own P0 was found the
 * same way — a test asserting that a mocked module is a thing rather than that
 * the thing works.
 *
 * So only the leaves are mocked here: `../api` (the HTTP client) and the four
 * picker-data hooks whose data this page does not own. `../hooks/useWorlds` is
 * the real module, and the URL it calls is asserted directly.
 */
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockApi = vi.hoisted(() => ({
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
}));

const mockConfirm = vi.hoisted(() => vi.fn());
const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
const mockCharacters = vi.hoisted(() => vi.fn());
const mockStories = vi.hoisted(() => vi.fn());
const mockChats = vi.hoisted(() => vi.fn());
const mockLocations = vi.hoisted(() => vi.fn());

vi.mock('../api', () => ({ api: mockApi }));

vi.mock('../hooks/useCharacters', () => ({
    useCharacters: (...args) => mockCharacters(...args),
}));

vi.mock('../hooks/useStories', () => ({
    useStories: (...args) => mockStories(...args),
}));

vi.mock('../hooks/useChats', () => ({
    useChats: (...args) => mockChats(...args),
}));

vi.mock('../hooks/useLocations', () => ({
    useLocations: (...args) => mockLocations(...args),
}));

vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: mockConfirm }),
}));

vi.mock('react-hot-toast', () => ({
    default: mockToast,
}));

const DEFAULT_WORLDS = [
    {
        id: 'world-1',
        name: 'Age of Embers',
        description: 'A dragon war epic',
        character_ids: ['char-1', 'char-2'],
        story_ids: ['s-1', 's-2', 's-3'],
        chat_ids: ['chat-1', 'chat-2', 'chat-3', 'chat-4'],
        location_ids: ['loc-1', 'loc-2', 'loc-3', 'loc-4', 'loc-5'],
    },
    {
        id: 'world-2',
        name: 'Silent Waters',
        description: 'An underwater chronicle',
        character_ids: [],
        story_ids: [],
        chat_ids: [],
        location_ids: [],
    },
];

const DASHBOARD = {
    world: { id: 'world-1', name: 'Age of Embers', description: 'A dragon war epic' },
    characters: [
        { id: 'char-1', name: 'Aria' },
        { id: 'char-2', name: 'Zed' },
    ],
    stories: [{ id: 's-1', title: 'The Dragon War' }],
    chats: [{ id: 'chat-1', name: 'War Council' }],
    locations: [],
};

const PICKER_DATA = {
    characters: [
        { id: 'char-1', name: 'Aria' },
        { id: 'char-2', name: 'Zed' },
    ],
    stories: [{ id: 's-1', title: 'The Dragon War' }],
    chats: [{ id: 'chat-1', name: 'War Council' }],
    locations: [{ id: 'loc-1', name: 'Cinderfall' }],
};

function makeClient() {
    return new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
}

function PathProbe() {
    const { pathname } = useLocation();
    return <div data-testid="pathname">{pathname}</div>;
}

function renderWorlds() {
    const queryClient = makeClient();
    const utils = render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={['/worlds']}>
                <Worlds />
                <PathProbe />
            </MemoryRouter>
        </QueryClientProvider>,
    );
    return { ...utils, queryClient };
}

let Worlds;

beforeEach(async () => {
    vi.clearAllMocks();
    // Imported per-test-file run so each test gets a fresh QueryClient-backed
    // cache; the module itself is real.
    Worlds = (await import('./Worlds')).default;
    mockApi.get.mockResolvedValue(DEFAULT_WORLDS);
    mockApi.post.mockResolvedValue({ id: 'world-new' });
    mockApi.put.mockResolvedValue({});
    mockApi.delete.mockResolvedValue({});
    mockCharacters.mockReturnValue({ data: PICKER_DATA.characters });
    mockStories.mockReturnValue({ data: PICKER_DATA.stories });
    mockChats.mockReturnValue({ data: PICKER_DATA.chats });
    mockLocations.mockReturnValue({ data: PICKER_DATA.locations });
    mockConfirm.mockResolvedValue(true);
});

describe('Worlds hook — the route it actually calls', () => {
    it('reads /api/v2/worlds, not the deleted /api/v2/campaigns', async () => {
        const { useWorlds } = await import('../hooks/useWorlds');
        const queryClient = makeClient();
        const { renderHook } = await import('@testing-library/react');
        const { createElement } = await import('react');

        renderHook(() => useWorlds(), {
            wrapper: ({ children }) => createElement(QueryClientProvider, { client: queryClient }, children),
        });

        await waitFor(() => expect(mockApi.get).toHaveBeenCalledTimes(1));
        expect(mockApi.get).toHaveBeenCalledWith('/api/v2/worlds');
        // The 404 that hid this defect for three audits, named explicitly.
        expect(mockApi.get).not.toHaveBeenCalledWith(expect.stringContaining('/api/v2/campaigns'));
    });

    it('creates, updates and deletes on /api/v2/worlds', async () => {
        const { useCreateWorld, useUpdateWorld, useDeleteWorld } = await import('../hooks/useWorlds');
        const queryClient = makeClient();
        const { renderHook } = await import('@testing-library/react');
        const { createElement } = await import('react');
        const wrapper = ({ children }) => createElement(QueryClientProvider, { client: queryClient }, children);

        const { result: create } = renderHook(() => useCreateWorld(), { wrapper });
        await act(async () => { await create.current.mutateAsync({ name: 'W' }); });
        expect(mockApi.post).toHaveBeenCalledWith('/api/v2/worlds', { name: 'W' });

        const { result: update } = renderHook(() => useUpdateWorld(), { wrapper });
        await act(async () => { await update.current.mutateAsync({ id: 'world-1', name: 'W2' }); });
        expect(mockApi.put).toHaveBeenCalledWith('/api/v2/worlds/world-1', { name: 'W2' });

        const { result: remove } = renderHook(() => useDeleteWorld(), { wrapper });
        await act(async () => { await remove.current.mutateAsync('world-1'); });
        expect(mockApi.delete).toHaveBeenCalledWith('/api/v2/worlds/world-1');
    });

    it('reads the dashboard from the world-scoped route', async () => {
        const { useWorldDashboard } = await import('../hooks/useWorlds');
        const queryClient = makeClient();
        const { renderHook } = await import('@testing-library/react');
        const { createElement } = await import('react');

        renderHook(() => useWorldDashboard('world-1'), {
            wrapper: ({ children }) => createElement(QueryClientProvider, { client: queryClient }, children),
        });

        await waitFor(() => expect(mockApi.get).toHaveBeenCalledWith('/api/v2/worlds/world-1/dashboard'));
    });
});

describe('Worlds page', () => {
    it('renders the page heading, subtitle, search box, and New World button', async () => {
        renderWorlds();
        expect(await screen.findByRole('heading', { name: 'Worlds' })).toBeInTheDocument();
        expect(screen.getByText(/organize your characters/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Search worlds...')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /new world/i })).toBeInTheDocument();
    });

    it('shows loading skeletons while fetching', async () => {
        let resolveList;
        mockApi.get.mockImplementation(() => new Promise((resolve) => { resolveList = resolve; }));
        const { container } = renderWorlds();

        await waitFor(() => expect(container.querySelector('.animate-pulse')).toBeInTheDocument());
        expect(screen.queryByText('Age of Embers')).not.toBeInTheDocument();

        await act(async () => { resolveList(DEFAULT_WORLDS); });
        expect(await screen.findByText('Age of Embers')).toBeInTheDocument();
    });

    it('shows an empty state only when the list really is empty', async () => {
        mockApi.get.mockResolvedValue([]);
        renderWorlds();
        expect(await screen.findByText('No worlds yet')).toBeInTheDocument();
        expect(screen.getByText(/create your first world/i)).toBeInTheDocument();
    });

    // The regression this file exists for. `/api/v2/campaigns` 404'd, the page
    // destructured only `{ data, isLoading }`, and the result was a working-looking
    // empty state with a working-looking "New Campaign" button. A failed fetch and
    // an empty vault were indistinguishable.
    it('reports a failed fetch instead of rendering a plausible empty state', async () => {
        mockApi.get.mockRejectedValue(Object.assign(new Error('Request failed with status code 404'), { status: 404 }));
        renderWorlds();

        const alert = await screen.findByRole('alert');
        expect(alert).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: /could not load your worlds/i })).toBeInTheDocument();
        expect(screen.queryByText('No worlds yet')).not.toBeInTheDocument();
        // The "create" affordance that made the old failure look like a working
        // empty state.
        expect(screen.getByRole('button', { name: /new world/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    });

    it('retries on demand from the error state', async () => {
        mockApi.get.mockRejectedValueOnce(new Error('down'));
        renderWorlds();
        await screen.findByRole('alert');

        mockApi.get.mockResolvedValue(DEFAULT_WORLDS);
        fireEvent.click(screen.getByRole('button', { name: /try again/i }));

        expect(await screen.findByText('Age of Embers')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('renders world cards with names, descriptions, and entity counts', async () => {
        renderWorlds();
        expect(await screen.findByText('Age of Embers')).toBeInTheDocument();
        expect(screen.getByText('A dragon war epic')).toBeInTheDocument();
        expect(screen.getByText('Silent Waters')).toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
        expect(screen.getByText('4')).toBeInTheDocument();
        expect(screen.getByText('5')).toBeInTheDocument();
    });

    it('filters the world list by search query', async () => {
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.change(screen.getByPlaceholderText('Search worlds...'), { target: { value: 'silent' } });
        expect(screen.getByText('Silent Waters')).toBeInTheDocument();
        expect(screen.queryByText('Age of Embers')).not.toBeInTheDocument();
    });

    it('creates a world with linked entities from the pickers', async () => {
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getByRole('button', { name: /new world/i }));
        expect(screen.getAllByText('New World').length).toBeGreaterThan(0);
        fireEvent.change(screen.getByPlaceholderText('World name'), { target: { value: 'New Age' } });
        fireEvent.change(screen.getByPlaceholderText(/overview of this world/i), { target: { value: 'A test realm' } });
        fireEvent.click(screen.getByRole('button', { name: 'Aria' }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));

        await waitFor(() => {
            expect(mockApi.post).toHaveBeenCalledWith('/api/v2/worlds', {
                name: 'New Age',
                description: 'A test realm',
                character_ids: ['char-1'],
                story_ids: [],
                chat_ids: [],
                location_ids: [],
            });
        });
        expect(mockToast.success).toHaveBeenCalledWith('World created');
    });

    it('prevents creating a world without a name', async () => {
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getByRole('button', { name: /new world/i }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        expect(mockToast.error).toHaveBeenCalledWith('Name is required');
        expect(mockApi.post).not.toHaveBeenCalled();
    });

    it('shows picker empty hints when no entities are available', async () => {
        mockCharacters.mockReturnValue({ data: [] });
        mockStories.mockReturnValue({ data: [] });
        mockChats.mockReturnValue({ data: [] });
        mockLocations.mockReturnValue({ data: [] });
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getByRole('button', { name: /new world/i }));
        expect(screen.getByText('None available — create characters first')).toBeInTheDocument();
        expect(screen.getByText('None available — create stories first')).toBeInTheDocument();
        expect(screen.getByText('None available — create chats first')).toBeInTheDocument();
        expect(screen.getByText('None available — create locations first')).toBeInTheDocument();
    });

    it('edits an existing world with prefilled values', async () => {
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getAllByTitle('Edit')[0]);
        expect(screen.getByText('Edit World')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Age of Embers')).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('World name'), { target: { value: 'Age of Embers II' } });
        fireEvent.click(screen.getByRole('button', { name: /^update$/i }));

        await waitFor(() => {
            expect(mockApi.put).toHaveBeenCalledWith('/api/v2/worlds/world-1', expect.objectContaining({ name: 'Age of Embers II' }));
        });
        expect(mockToast.success).toHaveBeenCalledWith('World updated');
    });

    it('deletes a world after confirmation', async () => {
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({
                title: 'Delete World',
                message: 'Are you sure you want to delete "Age of Embers"?',
            }));
        });
        expect(mockApi.delete).toHaveBeenCalledWith('/api/v2/worlds/world-1');
        expect(mockToast.success).toHaveBeenCalledWith('World deleted');
    });

    it('does not delete when confirmation is cancelled', async () => {
        mockConfirm.mockResolvedValue(false);
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
        expect(mockApi.delete).not.toHaveBeenCalled();
    });

    it('opens the world dashboard showing linked entities', async () => {
        mockApi.get.mockImplementation((url) => (
            url.endsWith('/dashboard') ? Promise.resolve(DASHBOARD) : Promise.resolve(DEFAULT_WORLDS)
        ));
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getAllByTitle('Open')[0]);

        // Waits on the dashboard's own content, not on the card title the list
        // already rendered — the card is still mounted underneath the overlay.
        await waitFor(() => expect(screen.getByText('Characters (2)')).toBeInTheDocument());
        expect(screen.getByText('Aria')).toBeInTheDocument();
        expect(screen.getByText('Zed')).toBeInTheDocument();
        expect(screen.getByText('Stories (1)')).toBeInTheDocument();
        expect(screen.getByText('Chats (1)')).toBeInTheDocument();
        expect(screen.getByText('Locations (0)')).toBeInTheDocument();
        expect(screen.getByText('None yet')).toBeInTheDocument();
    });

    it('navigates from the dashboard when a linked chat is opened', async () => {
        mockApi.get.mockImplementation((url) => (
            url.endsWith('/dashboard') ? Promise.resolve(DASHBOARD) : Promise.resolve(DEFAULT_WORLDS)
        ));
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getAllByTitle('Open')[0]);
        await waitFor(() => expect(screen.getByText('War Council')).toBeInTheDocument());        fireEvent.click(screen.getByText('War Council'));
        await waitFor(() => {
            expect(screen.getByTestId('pathname')).toHaveTextContent('/chat/chat-1');
        });
    });

    it('closes the form modal on Escape', async () => {
        renderWorlds();
        await screen.findByText('Age of Embers');
        fireEvent.click(screen.getByRole('button', { name: /new world/i }));
        expect(screen.getByRole('dialog', { name: 'New World' })).toBeInTheDocument();
        fireEvent.keyDown(window, { key: 'Escape' });
        await waitFor(() => {
            expect(screen.queryByRole('dialog', { name: 'New World' })).not.toBeInTheDocument();
        });
    });
});
