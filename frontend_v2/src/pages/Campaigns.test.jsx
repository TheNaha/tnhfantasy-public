import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Campaigns from './Campaigns';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

const mockCampaigns = vi.hoisted(() => vi.fn());
const mockCreateCampaign = vi.hoisted(() => vi.fn());
const mockUpdateCampaign = vi.hoisted(() => vi.fn());
const mockDeleteCampaign = vi.hoisted(() => vi.fn());
const mockCampaignDashboard = vi.hoisted(() => vi.fn());
const mockCharacters = vi.hoisted(() => vi.fn());
const mockStories = vi.hoisted(() => vi.fn());
const mockChats = vi.hoisted(() => vi.fn());
const mockLocations = vi.hoisted(() => vi.fn());
const mockConfirm = vi.hoisted(() => vi.fn());
const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('../hooks/useCampaigns', () => ({
    useCampaigns: (...args) => mockCampaigns(...args),
    useCreateCampaign: (...args) => mockCreateCampaign(...args),
    useUpdateCampaign: (...args) => mockUpdateCampaign(...args),
    useDeleteCampaign: (...args) => mockDeleteCampaign(...args),
    useCampaignDashboard: (...args) => mockCampaignDashboard(...args),
}));

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

const DEFAULT_CAMPAIGNS = [
    {
        id: 'camp-1',
        name: 'Age of Embers',
        description: 'A dragon war epic',
        character_ids: ['char-1', 'char-2'],
        story_ids: ['s-1', 's-2', 's-3'],
        chat_ids: ['chat-1', 'chat-2', 'chat-3', 'chat-4'],
        location_ids: ['loc-1', 'loc-2', 'loc-3', 'loc-4', 'loc-5'],
    },
    {
        id: 'camp-2',
        name: 'Silent Waters',
        description: 'An underwater chronicle',
        character_ids: [],
        story_ids: [],
        chat_ids: [],
        location_ids: [],
    },
];

const DEFAULT_PICKER_DATA = {
    characters: [
        { id: 'char-1', name: 'Aria' },
        { id: 'char-2', name: 'Zed' },
    ],
    stories: [{ id: 's-1', title: 'The Dragon War' }],
    chats: [{ id: 'chat-1', name: 'War Council' }],
    locations: [{ id: 'loc-1', name: 'Cinderfall' }],
};

const DEFAULT_DASHBOARD = {
    isLoading: false,
    data: {
        campaign: { name: 'Age of Embers' },
        description: 'A dragon war epic',
        characters: [
            { id: 'char-1', name: 'Aria' },
            { id: 'char-2', name: 'Zed' },
        ],
        stories: [{ id: 's-1', title: 'The Dragon War' }],
        chats: [{ id: 'chat-1', name: 'War Council' }],
        locations: [],
    },
};

function PathProbe() {
    const { pathname } = useLocation();
    return <div data-testid="pathname">{pathname}</div>;
}

function renderWithProviders(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            {/* Campaigns uses useNavigate (dashboard modal) and EmptyState uses useNavigate too */}
            <MemoryRouter initialEntries={['/campaigns']}>
                {ui}
                <PathProbe />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('Campaigns page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockCampaigns.mockReturnValue({ data: DEFAULT_CAMPAIGNS, isLoading: false });
        mockCreateCampaign.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ id: 'new-camp' }), isPending: false });
        mockUpdateCampaign.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
        mockDeleteCampaign.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockCampaignDashboard.mockReturnValue(DEFAULT_DASHBOARD);
        mockCharacters.mockReturnValue({ data: DEFAULT_PICKER_DATA.characters });
        mockStories.mockReturnValue({ data: DEFAULT_PICKER_DATA.stories });
        mockChats.mockReturnValue({ data: DEFAULT_PICKER_DATA.chats });
        mockLocations.mockReturnValue({ data: DEFAULT_PICKER_DATA.locations });
        mockConfirm.mockResolvedValue(true);
    });

    it('renders the page heading, subtitle, search box, and New Campaign button', () => {
        renderWithProviders(<Campaigns />);
        expect(screen.getByRole('heading', { name: 'Campaigns' })).toBeInTheDocument();
        expect(screen.getByText(/organize your stories/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Search campaigns...')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /new campaign/i })).toBeInTheDocument();
    });

    it('shows loading skeletons while fetching campaigns', () => {
        mockCampaigns.mockReturnValue({ data: [], isLoading: true });
        const { container } = renderWithProviders(<Campaigns />);
        expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
        expect(screen.queryByText('Age of Embers')).not.toBeInTheDocument();
    });

    it('shows an empty state when there are no campaigns', () => {
        mockCampaigns.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<Campaigns />);
        expect(screen.getByText('No campaigns yet')).toBeInTheDocument();
        expect(screen.getByText(/create your first campaign/i)).toBeInTheDocument();
    });

    it('renders campaign cards with names, descriptions, and entity counts', () => {
        renderWithProviders(<Campaigns />);
        expect(screen.getByText('Age of Embers')).toBeInTheDocument();
        expect(screen.getByText('A dragon war epic')).toBeInTheDocument();
        expect(screen.getByText('Silent Waters')).toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
        expect(screen.getByText('4')).toBeInTheDocument();
        expect(screen.getByText('5')).toBeInTheDocument();
    });

    it('filters the campaign list by search query', () => {
        renderWithProviders(<Campaigns />);
        fireEvent.change(screen.getByPlaceholderText('Search campaigns...'), { target: { value: 'silent' } });
        expect(screen.getByText('Silent Waters')).toBeInTheDocument();
        expect(screen.queryByText('Age of Embers')).not.toBeInTheDocument();
    });

    it('creates a campaign with linked entities from the pickers', async () => {
        const mutate = vi.fn().mockResolvedValue({ id: 'new-camp' });
        mockCreateCampaign.mockReturnValue({ mutateAsync: mutate, isPending: false });
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getByRole('button', { name: /new campaign/i }));
        expect(screen.getAllByText('New Campaign').length).toBeGreaterThan(0);
        fireEvent.change(screen.getByPlaceholderText('Campaign name'), { target: { value: 'New Age' } });
        fireEvent.change(screen.getByPlaceholderText(/overview of this campaign/i), { target: { value: 'A test chronicle' } });
        fireEvent.click(screen.getByRole('button', { name: 'Aria' }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        await waitFor(() => {
            expect(mutate).toHaveBeenCalledWith({
                name: 'New Age',
                description: 'A test chronicle',
                character_ids: ['char-1'],
                story_ids: [],
                chat_ids: [],
                location_ids: [],
            });
        });
        expect(mockToast.success).toHaveBeenCalledWith('Campaign created');
    });

    it('prevents creating a campaign without a name', async () => {
        const mutate = vi.fn();
        mockCreateCampaign.mockReturnValue({ mutateAsync: mutate });
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getByRole('button', { name: /new campaign/i }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        expect(mockToast.error).toHaveBeenCalledWith('Name is required');
        expect(mutate).not.toHaveBeenCalled();
    });

    it('shows picker empty hints when no entities are available', () => {
        mockCharacters.mockReturnValue({ data: [] });
        mockStories.mockReturnValue({ data: [] });
        mockChats.mockReturnValue({ data: [] });
        mockLocations.mockReturnValue({ data: [] });
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getByRole('button', { name: /new campaign/i }));
        expect(screen.getByText('None available — create characters first')).toBeInTheDocument();
        expect(screen.getByText('None available — create stories first')).toBeInTheDocument();
        expect(screen.getByText('None available — create chats first')).toBeInTheDocument();
        expect(screen.getByText('None available — create locations first')).toBeInTheDocument();
    });

    it('edits an existing campaign with prefilled values', async () => {
        const mutate = vi.fn().mockResolvedValue({});
        mockUpdateCampaign.mockReturnValue({ mutateAsync: mutate, isPending: false });
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getAllByTitle('Edit')[0]);
        expect(screen.getByText('Edit Campaign')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Age of Embers')).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('Campaign name'), { target: { value: 'Age of Embers II' } });
        fireEvent.click(screen.getByRole('button', { name: /^update$/i }));
        await waitFor(() => {
            expect(mutate).toHaveBeenCalledWith(expect.objectContaining({ id: 'camp-1', name: 'Age of Embers II' }));
        });
        expect(mockToast.success).toHaveBeenCalledWith('Campaign updated');
    });

    it('deletes a campaign after confirmation', async () => {
        const mutate = vi.fn().mockResolvedValue({});
        mockDeleteCampaign.mockReturnValue({ mutateAsync: mutate });
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({
                title: 'Delete Campaign',
                message: 'Are you sure you want to delete "Age of Embers"?',
            }));
        });
        expect(mutate).toHaveBeenCalledWith('camp-1');
        expect(mockToast.success).toHaveBeenCalledWith('Campaign deleted');
    });

    it('does not delete when confirmation is cancelled', async () => {
        mockConfirm.mockResolvedValue(false);
        const mutate = vi.fn();
        mockDeleteCampaign.mockReturnValue({ mutateAsync: mutate });
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalled();
        });
        expect(mutate).not.toHaveBeenCalled();
    });

    it('opens the campaign dashboard showing linked entities', async () => {
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getAllByTitle('Open')[0]);
        await waitFor(() => {
            expect(screen.getAllByText('Age of Embers').length).toBeGreaterThan(0);
        });
        expect(screen.getByText('Characters (2)')).toBeInTheDocument();
        expect(screen.getByText('Aria')).toBeInTheDocument();
        expect(screen.getByText('Zed')).toBeInTheDocument();
        expect(screen.getByText('Stories (1)')).toBeInTheDocument();
        expect(screen.getByText('Chats (1)')).toBeInTheDocument();
        expect(screen.getByText('Locations (0)')).toBeInTheDocument();
        expect(screen.getByText('None yet')).toBeInTheDocument();
    });

    it('navigates from the dashboard when a linked chat is opened', async () => {
        renderWithProviders(<Campaigns />);
        fireEvent.click(screen.getAllByTitle('Open')[0]);
        await waitFor(() => {
            expect(screen.getByText('War Council')).toBeInTheDocument();
        });
        fireEvent.click(screen.getByText('War Council'));
        await waitFor(() => {
            expect(screen.getByTestId('pathname')).toHaveTextContent('/chat/chat-1');
        });
    });
});