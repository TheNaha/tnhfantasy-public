import { render, screen, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Activity from './Activity';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

const mockTimeline = vi.hoisted(() => vi.fn());
const mockNavigate = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useTimeline', () => ({
    useTimeline: (...args) => mockTimeline(...args),
}));

vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock('../hooks/useCharacters', () => ({
    useCharacters: () => ({ data: [{ id: 'c-1', name: 'Aria' }] }),
}));

vi.mock('../hooks/useStories', () => ({
    useStories: () => ({ data: [{ id: 's-1', title: 'Test Story' }] }),
}));

vi.mock('../hooks/useChats', () => ({
    useChats: () => ({ data: [{ id: 'ch-1', name: 'Test Chat' }] }),
}));

vi.mock('../hooks/useLocations', () => ({
    useLocations: () => ({ data: [{ id: 'l-1', name: 'Test Location' }] }),
}));

vi.mock('../hooks/useWorlds', () => ({
    useWorlds: () => ({ data: [{ id: 'w-1', name: 'Emberfall' }] }),
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
        g: ({ children, ...props }) => {
            const safe = {};
            for (const k of Object.keys(props)) {
                if (!['initial', 'animate', 'exit', 'whileHover', 'whileTap', 'transition', 'variants', 'layout'].includes(k)) {
                    safe[k] = props[k];
                }
            }
            return <g {...safe}>{children}</g>;
        },
        span: ({ children }) => <span>{children}</span>,
    },
    AnimatePresence: ({ children }) => <>{children}</>,
}));

const eventsData = {
    events: [
        { id: 'm1', type: 'message', timestamp: '2026-08-10T14:30:00', title: 'Aria greets the party', description: 'A cheerful hello', chat_id: 'ch-1' },
        { id: 'ch1', type: 'chapter', timestamp: '2026-08-10T18:05:00', title: 'Chapter 5 written', description: 'The battle begins', story_id: 's-1' },
        { id: 'mem1', type: 'memory', timestamp: '2026-08-11T09:15:00', title: 'Memory consolidated' },
    ],
};

function renderWithProviders(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>{ui}</MemoryRouter>
        </QueryClientProvider>
    );
}

describe('Activity page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockNavigate.mockReset();
        mockTimeline.mockReturnValue({ data: eventsData, isLoading: false });
    });

    it('renders the main heading, description, and filters toggle', () => {
        renderWithProviders(<Activity />);
        expect(screen.getByRole('heading', { name: 'Activity' })).toBeInTheDocument();
        expect(screen.getByText(/Everything that has happened in your vault/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /filters/i })).toBeInTheDocument();
    });

    it('shows a loading skeleton while fetching events', () => {
        mockTimeline.mockReturnValue({ data: undefined, isLoading: true });
        const { container } = renderWithProviders(<Activity />);
        expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
        expect(screen.queryByText('No events yet')).not.toBeInTheDocument();
    });

    it('shows an empty state when there are no events', () => {
        mockTimeline.mockReturnValue({ data: { events: [] }, isLoading: false });
        renderWithProviders(<Activity />);
        expect(screen.getByText('No events yet')).toBeInTheDocument();
        expect(screen.getByText(/Start chatting, writing stories/i)).toBeInTheDocument();
    });

    it('shows an error, not an empty feed, when the timeline request fails', () => {
        // The defect this pins: the page had no `isError` branch at all, so a
        // failed fetch rendered "No events yet" — telling the user their whole
        // world was empty when the request had simply failed. Same class as the
        // `Worlds.jsx` P0 from the 2026-09-29b audit, in the next page over.
        mockTimeline.mockReturnValue({
            data: undefined,
            isLoading: false,
            isError: true,
            error: new Error('timeline exploded'),
        });
        renderWithProviders(<Activity />);

        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText(/Couldn't load activity/i)).toBeInTheDocument();
        expect(screen.getByText('timeline exploded')).toBeInTheDocument();
        expect(screen.queryByText('No events yet')).not.toBeInTheDocument();
    });

    it('renders events grouped by date with titles, type labels, and timestamps', () => {
        renderWithProviders(<Activity />);
        expect(screen.getByText('2026-08-11')).toBeInTheDocument();
        expect(screen.getByText('2026-08-10')).toBeInTheDocument();
        expect(screen.getByText('Aria greets the party')).toBeInTheDocument();
        expect(screen.getByText('A cheerful hello')).toBeInTheDocument();
        expect(screen.getByText('Chapter 5 written')).toBeInTheDocument();
        expect(screen.getByText('Memory consolidated')).toBeInTheDocument();
        expect(screen.getByText('Message')).toBeInTheDocument();
        expect(screen.getByText('Chapter')).toBeInTheDocument();
        expect(screen.getByText('Memory')).toBeInTheDocument();
        expect(screen.getByText('14:30:00')).toBeInTheDocument();
    });

    it('toggles the filter panel open and closed', () => {
        renderWithProviders(<Activity />);
        const filtersButton = screen.getByRole('button', { name: /filters/i });
        fireEvent.click(filtersButton);
        expect(screen.getByLabelText('Character')).toBeInTheDocument();
        expect(screen.getByLabelText('Story')).toBeInTheDocument();
        expect(screen.getByLabelText('Chat')).toBeInTheDocument();
        expect(screen.getByLabelText('Location')).toBeInTheDocument();
        fireEvent.click(filtersButton);
        expect(screen.queryByLabelText('Character')).not.toBeInTheDocument();
    });

    it('passes updated filters to the timeline hook when a filter is selected', () => {
        renderWithProviders(<Activity />);
        fireEvent.click(screen.getByRole('button', { name: /filters/i }));
        fireEvent.change(screen.getByLabelText('Character'), {
            target: { value: 'c-1' },
        });
        expect(mockTimeline).toHaveBeenLastCalledWith(
            expect.objectContaining({ character_id: 'c-1' })
        );
    });

    it('navigates to the source entity when an event card is clicked', () => {
        renderWithProviders(<Activity />);
        fireEvent.click(screen.getByTitle('Open chat'));
        expect(mockNavigate).toHaveBeenCalledWith('/chat/ch-1');
        fireEvent.click(screen.getByTitle('Open story'));
        expect(mockNavigate).toHaveBeenCalledWith('/story/s-1');
    });

    it('shows a load-more control and grows the page size when more events exist', () => {
        mockTimeline.mockReturnValue({ data: { ...eventsData, total: 150 }, isLoading: false });
        renderWithProviders(<Activity />);
        expect(screen.getByText('Showing 3 of 150 events')).toBeInTheDocument();
        const loadMore = screen.getByRole('button', { name: /load more/i });
        fireEvent.click(loadMore);
        expect(mockTimeline).toHaveBeenLastCalledWith(
            expect.objectContaining({ limit: 200 })
        );
    });
});

describe('Activity page — filters that could never match', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockNavigate.mockReset();
        mockTimeline.mockReturnValue({ data: eventsData, isLoading: false });
    });

    const openFilters = () => {
        renderWithProviders(<Activity />);
        fireEvent.click(screen.getByRole('button', { name: /filters/i }));
    };

    it('sends the location NAME, because the route matches a free-text column', () => {
        openFilters();
        const select = screen.getByLabelText('Location');
        const option = within(select).getByRole('option', { name: 'Test Location' });
        // `timeline.py` compares `?location=` against `Chat.story_location`.
        // It was being handed the Location's UUID, which no chat can hold.
        expect(option).toHaveValue('Test Location');
        expect(option).not.toHaveValue('l-1');

        fireEvent.change(select, { target: { value: 'Test Location' } });
        expect(mockTimeline).toHaveBeenLastCalledWith(
            expect.objectContaining({ location: 'Test Location' })
        );
    });

    it('offers a world filter and passes it as the worldId timeline option', () => {
        openFilters();
        const select = screen.getByLabelText('World');
        expect(within(select).getByRole('option', { name: 'Emberfall' })).toHaveValue('w-1');

        fireEvent.change(select, { target: { value: 'w-1' } });
        expect(mockTimeline).toHaveBeenLastCalledWith(
            expect.objectContaining({ worldId: 'w-1' })
        );
    });

    it('says plainly that a story filter does not scope chat messages', () => {
        openFilters();
        expect(
            screen.getByText(/Chat messages are not filtered by story/i)
        ).toBeInTheDocument();
        // and the caveat is also in the page's own description, not only behind
        // the Filters disclosure
        expect(screen.getByText(/never chat messages/i)).toBeInTheDocument();
    });

    it('flags that the character filter matches a chat main character, not a speaker', () => {
        openFilters();
        expect(
            screen.getByText(/Matches a chat's main character, not who spoke/i)
        ).toBeInTheDocument();
    });
});