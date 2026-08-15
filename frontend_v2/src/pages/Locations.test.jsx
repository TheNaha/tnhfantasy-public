import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Locations from './Locations';

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

const mockLocations = vi.hoisted(() => vi.fn());
const mockCreateLocation = vi.hoisted(() => vi.fn());
const mockUpdateLocation = vi.hoisted(() => vi.fn());
const mockDeleteLocation = vi.hoisted(() => vi.fn());
const mockConfirm = vi.hoisted(() => vi.fn());
const mockToast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock('../hooks/useLocations', () => ({
    useLocations: (...args) => mockLocations(...args),
    useCreateLocation: (...args) => mockCreateLocation(...args),
    useUpdateLocation: (...args) => mockUpdateLocation(...args),
    useDeleteLocation: (...args) => mockDeleteLocation(...args),
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

const DEFAULT_LOCATIONS = [
    { id: 'loc-1', name: 'Castle Black', description: 'A fortress of ice', atmosphere: 'Cold and silent', tags: ['north', 'castle'] },
    { id: 'loc-2', name: 'The Green Tavern', description: 'A cozy inn', atmosphere: 'Warm and loud', tags: ['forest'] },
];

function renderWithProviders(ui) {
    return render(
        <QueryClientProvider client={queryClient}>
            {/* EmptyState uses useNavigate, so the page must render inside a router */}
            <MemoryRouter initialEntries={['/locations']}>
                {ui}
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('Locations page', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockLocations.mockReturnValue({ data: DEFAULT_LOCATIONS, isLoading: false });
        mockCreateLocation.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({ id: 'new-loc' }), isPending: false });
        mockUpdateLocation.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false });
        mockDeleteLocation.mockReturnValue({ mutateAsync: vi.fn().mockResolvedValue({}) });
        mockConfirm.mockResolvedValue(true);
    });

    it('renders the page heading, subtitle, search box, and New Location button', () => {
        renderWithProviders(<Locations />);
        expect(screen.getByRole('heading', { name: 'Locations' })).toBeInTheDocument();
        expect(screen.getByText(/world-building locations/i)).toBeInTheDocument();
        expect(screen.getByPlaceholderText('Search locations...')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /new location/i })).toBeInTheDocument();
    });

    it('shows loading skeletons while fetching locations', () => {
        mockLocations.mockReturnValue({ data: [], isLoading: true });
        const { container } = renderWithProviders(<Locations />);
        expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
        expect(screen.queryByText('Castle Black')).not.toBeInTheDocument();
    });

    it('shows an empty state when there are no locations', () => {
        mockLocations.mockReturnValue({ data: [], isLoading: false });
        renderWithProviders(<Locations />);
        expect(screen.getByText('No locations yet')).toBeInTheDocument();
        expect(screen.getByText(/create your first location/i)).toBeInTheDocument();
    });

    it('renders location cards with name, description, atmosphere, and tags', () => {
        renderWithProviders(<Locations />);
        expect(screen.getByText('Castle Black')).toBeInTheDocument();
        expect(screen.getByText('A fortress of ice')).toBeInTheDocument();
        expect(screen.getByText('Cold and silent')).toBeInTheDocument();
        expect(screen.getByText('north')).toBeInTheDocument();
        expect(screen.getByText('castle')).toBeInTheDocument();
        expect(screen.getByText('The Green Tavern')).toBeInTheDocument();
        expect(screen.getByText('forest')).toBeInTheDocument();
    });

    it('filters the location list by search query', () => {
        renderWithProviders(<Locations />);
        fireEvent.change(screen.getByPlaceholderText('Search locations...'), { target: { value: 'castle' } });
        expect(screen.getByText('Castle Black')).toBeInTheDocument();
        expect(screen.queryByText('The Green Tavern')).not.toBeInTheDocument();
    });

    it('creates a new location with tags when the form is submitted', async () => {
        const mutate = vi.fn().mockResolvedValue({ id: 'new-loc' });
        mockCreateLocation.mockReturnValue({ mutateAsync: mutate, isPending: false });
        renderWithProviders(<Locations />);
        fireEvent.click(screen.getByRole('button', { name: /new location/i }));
        expect(screen.getAllByText('New Location').length).toBeGreaterThan(0);
        fireEvent.change(screen.getByPlaceholderText('Location name'), { target: { value: 'The Shattered Keep' } });
        fireEvent.change(screen.getByPlaceholderText(/vivid description/i), { target: { value: 'A ruined fortress' } });
        fireEvent.change(screen.getByPlaceholderText('Add tag...'), { target: { value: 'dungeon' } });
        fireEvent.click(screen.getByRole('button', { name: /^add$/i }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        await waitFor(() => {
            expect(mutate).toHaveBeenCalledWith({
                name: 'The Shattered Keep',
                description: 'A ruined fortress',
                atmosphere: '',
                tags: ['dungeon'],
                image_path: '',
            });
        });
        expect(mockToast.success).toHaveBeenCalledWith('Location created');
    });

    it('prevents creating a location without a name', async () => {
        const mutate = vi.fn();
        mockCreateLocation.mockReturnValue({ mutateAsync: mutate });
        renderWithProviders(<Locations />);
        fireEvent.click(screen.getByRole('button', { name: /new location/i }));
        fireEvent.click(screen.getByRole('button', { name: /^create$/i }));
        expect(mockToast.error).toHaveBeenCalledWith('Name is required');
        expect(mutate).not.toHaveBeenCalled();
    });

    it('edits an existing location and submits the update', async () => {
        const mutate = vi.fn().mockResolvedValue({});
        mockUpdateLocation.mockReturnValue({ mutateAsync: mutate, isPending: false });
        renderWithProviders(<Locations />);
        fireEvent.click(screen.getAllByTitle('Edit')[0]);
        expect(screen.getByText('Edit Location')).toBeInTheDocument();
        expect(screen.getByDisplayValue('Castle Black')).toBeInTheDocument();
        fireEvent.change(screen.getByPlaceholderText('Location name'), { target: { value: 'Castle Black Remastered' } });
        fireEvent.click(screen.getByRole('button', { name: /^update$/i }));
        await waitFor(() => {
            expect(mutate).toHaveBeenCalledWith(expect.objectContaining({ id: 'loc-1', name: 'Castle Black Remastered' }));
        });
        expect(mockToast.success).toHaveBeenCalledWith('Location updated');
    });

    it('deletes a location after confirmation', async () => {
        const mutate = vi.fn().mockResolvedValue({});
        mockDeleteLocation.mockReturnValue({ mutateAsync: mutate });
        renderWithProviders(<Locations />);
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({
                title: 'Delete Location',
                message: 'Are you sure you want to delete "Castle Black"?',
            }));
        });
        expect(mutate).toHaveBeenCalledWith('loc-1');
        expect(mockToast.success).toHaveBeenCalledWith('Location deleted');
    });

    it('does not delete when confirmation is cancelled', async () => {
        mockConfirm.mockResolvedValue(false);
        const mutate = vi.fn();
        mockDeleteLocation.mockReturnValue({ mutateAsync: mutate });
        renderWithProviders(<Locations />);
        fireEvent.click(screen.getAllByTitle('Delete')[0]);
        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalled();
        });
        expect(mutate).not.toHaveBeenCalled();
    });
});