import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import WorldTimeline from './WorldTimeline';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

const mockTimeline = vi.hoisted(() => vi.fn());

vi.mock('../hooks/useTimeline', () => ({
    useTimeline: (...args) => mockTimeline(...args),
}));

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
        { id: 'm1', type: 'message', timestamp: '2026-08-10T14:30:00', title: 'Aria greets the party', description: 'A cheerful hello' },
        { id: 'ch1', type: 'chapter', timestamp: '2026-08-10T18:05:00', title: 'Chapter 5 written', description: 'The battle begins' },
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

describe('WorldTimeline page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockTimeline.mockReturnValue({ data: eventsData, isLoading: false });
    });

    it('renders the main heading, description, and filters toggle', () => {
        renderWithProviders(<WorldTimeline />);
        expect(screen.getByRole('heading', { name: 'World Timeline' })).toBeInTheDocument();
        expect(screen.getByText(/Chronological view of all events/i)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /filters/i })).toBeInTheDocument();
    });

    it('shows a loading skeleton while fetching events', () => {
        mockTimeline.mockReturnValue({ data: undefined, isLoading: true });
        const { container } = renderWithProviders(<WorldTimeline />);
        expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
        expect(screen.queryByText('No events yet')).not.toBeInTheDocument();
    });

    it('shows an empty state when there are no events', () => {
        mockTimeline.mockReturnValue({ data: { events: [] }, isLoading: false });
        renderWithProviders(<WorldTimeline />);
        expect(screen.getByText('No events yet')).toBeInTheDocument();
        expect(screen.getByText(/Start chatting, writing stories/i)).toBeInTheDocument();
    });

    it('renders events grouped by date with titles, type labels, and timestamps', () => {
        renderWithProviders(<WorldTimeline />);
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
        renderWithProviders(<WorldTimeline />);
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
        renderWithProviders(<WorldTimeline />);
        fireEvent.click(screen.getByRole('button', { name: /filters/i }));
        fireEvent.change(screen.getByLabelText('Character'), {
            target: { value: 'c-1' },
        });
        expect(mockTimeline).toHaveBeenLastCalledWith(
            expect.objectContaining({ character_id: 'c-1' })
        );
    });
});