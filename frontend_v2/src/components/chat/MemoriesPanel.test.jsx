import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import MemoriesPanel from './MemoriesPanel';

const mockMemories = [
    { id: 'mem-1', character_id: 'char-1', content: 'The hero was born under a full moon.', importance: 8, tags: ['birth', 'omen'], created_at: '2024-01-15T10:00:00Z', last_accessed_at: null },
    { id: 'mem-2', character_id: 'char-1', content: 'Trust no one in the Shadowfell.', importance: 5, tags: ['warning', 'shadowfell'], created_at: '2024-02-20T12:00:00Z', last_accessed_at: '2024-03-01T08:00:00Z' },
];

const mockConfirm = vi.hoisted(() => vi.fn());

vi.mock('../../hooks/useMemories', () => ({
    useCharacterMemories: vi.fn(),
    useCreateMemory: vi.fn(),
    useDeleteMemory: vi.fn(),
    useSearchMemories: vi.fn(),
}));

vi.mock('../../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: mockConfirm }),
}));

vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn() },
    toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('lucide-react', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual };
});

import {
    useCharacterMemories,
    useCreateMemory,
    useDeleteMemory,
    useSearchMemories,
} from '../../hooks/useMemories';

function createWrapper() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return {
        wrapper: ({ children }) =>
            <MemoryRouter><QueryClientProvider client={queryClient}>{children}</QueryClientProvider></MemoryRouter>,
        queryClient,
    };
}

const mockMutateAsync = vi.fn();

describe('MemoriesPanel', () => {
    beforeEach(() => {
        vi.clearAllMocks();

        useCharacterMemories.mockReturnValue({ data: mockMemories, isLoading: false });
        useCreateMemory.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
        useDeleteMemory.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
        useSearchMemories.mockReturnValue({ data: null, isLoading: false });
        mockConfirm.mockResolvedValue(true);
    });

    it('renders the panel header with search and add button', () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        expect(screen.getByPlaceholderText('Semantic search…')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Add' })).toBeInTheDocument();
    });

    it('renders memory list when data is loaded', () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        expect(screen.getByText('The hero was born under a full moon.')).toBeInTheDocument();
        expect(screen.getByText('Trust no one in the Shadowfell.')).toBeInTheDocument();
        expect(screen.getByText(/2 memories/)).toBeInTheDocument();
    });

    it('shows loading skeleton while memories are loading', () => {
        useCharacterMemories.mockReturnValue({ data: [], isLoading: true });
        const { wrapper } = createWrapper();
        const { container } = render(<MemoriesPanel characterId="char-1" />, { wrapper });

        // The skeleton uses animate-pulse class
        expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
    });

    it('shows empty state when no memories exist', () => {
        useCharacterMemories.mockReturnValue({ data: [], isLoading: false });
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        expect(screen.getByText('No memories yet')).toBeInTheDocument();
        expect(screen.getByText('Add the first memory for this character.')).toBeInTheDocument();
    });

    it('shows no-results message when search returns empty', async () => {
        useCharacterMemories.mockReturnValue({ data: mockMemories, isLoading: false });
        useSearchMemories.mockReturnValue({ data: [], isLoading: false });
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        fireEvent.change(screen.getByPlaceholderText('Semantic search…'), { target: { value: 'xyz' } });

        await waitFor(() => {
            expect(screen.getByText('No matches found')).toBeInTheDocument();
        });
    });

    it('shows search match count when results are found', async () => {
        useCharacterMemories.mockReturnValue({ data: mockMemories, isLoading: false });
        useSearchMemories.mockReturnValue({ data: [mockMemories[0]], isLoading: false });
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        fireEvent.change(screen.getByPlaceholderText('Semantic search…'), { target: { value: 'moon' } });

        await waitFor(() => {
            expect(screen.getByText(/1 semantic match/)).toBeInTheDocument();
        });
    });

    it('toggles the add form when the Add button is clicked', () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        // Form is hidden initially
        expect(screen.queryByPlaceholderText('Memory content…')).not.toBeInTheDocument();

        // Click Add to show the form
        fireEvent.click(screen.getByRole('button', { name: /Add/i }));
        expect(screen.getByPlaceholderText('Memory content…')).toBeInTheDocument();

        // Click Cancel to hide
        fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
        expect(screen.queryByPlaceholderText('Memory content…')).not.toBeInTheDocument();
    });

    it('creates a memory with correct payload when form is submitted', async () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        // Open add form
        fireEvent.click(screen.getByRole('button', { name: /Add/i }));

        // Fill in the form
        fireEvent.change(screen.getByPlaceholderText('Memory content…'), { target: { value: 'A secret memory' } });
        // The importance slider is a range input — find via container
        fireEvent.change(screen.getByDisplayValue('5'), { target: { value: '7' } });
        fireEvent.change(screen.getByPlaceholderText('e.g. backstory, secret, combat'), { target: { value: 'secret, hidden' } });

        // Submit
        fireEvent.click(screen.getByText('Save Memory'));

        await waitFor(() => {
            expect(mockMutateAsync).toHaveBeenCalledWith({
                character_id: 'char-1',
                content: 'A secret memory',
                importance: 7,
                tags: ['secret', 'hidden'],
            });
        });
    });

    it('does not create memory when content is empty', () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        // Open add form
        fireEvent.click(screen.getByRole('button', { name: /Add/i }));

        // Submit without content
        fireEvent.click(screen.getByText('Save Memory'));

        expect(mockMutateAsync).not.toHaveBeenCalled();
    });

    it('shows spinner when creating is pending', () => {
        useCreateMemory.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: true });
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        fireEvent.click(screen.getByRole('button', { name: /Add/i }));
        // The spinner icon has animate-spin class
        const saveButton = screen.getByText('Save Memory');
        expect(saveButton).toBeInTheDocument();
        const spinner = saveButton.querySelector('.animate-spin');
        expect(spinner).toBeInTheDocument();
    });

    it('deletes a memory after confirmation', async () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        const deleteButtons = screen.getAllByTitle('Delete memory');
        fireEvent.click(deleteButtons[0]);

        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalledWith({
                title: 'Delete Memory',
                message: 'Remove this memory permanently?',
                confirmText: 'Delete',
                isDangerous: true,
            });
        });

        await waitFor(() => {
            expect(mockMutateAsync).toHaveBeenCalledWith({ id: 'mem-1', characterId: 'char-1' });
        });
    });

    it('does not delete memory when confirmation is cancelled', async () => {
        mockConfirm.mockResolvedValue(false);
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        const deleteButtons = screen.getAllByTitle('Delete memory');
        fireEvent.click(deleteButtons[0]);

        await waitFor(() => {
            expect(mockConfirm).toHaveBeenCalled();
        });

        expect(mockMutateAsync).not.toHaveBeenCalled();
    });

    it('renders tags for memories that have them', () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        expect(screen.getByText('birth')).toBeInTheDocument();
        expect(screen.getByText('omen')).toBeInTheDocument();
        expect(screen.getByText('shadowfell')).toBeInTheDocument();
    });

    it('renders importance dots with values', () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        // mem-1 has importance 8, mem-2 has importance 5
        expect(screen.getByText('8')).toBeInTheDocument();
        expect(screen.getByText('5')).toBeInTheDocument();
    });

    it('clears search when the X button is clicked', async () => {
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        const searchInput = screen.getByPlaceholderText('Semantic search…');
        fireEvent.change(searchInput, { target: { value: 'moon' } });

        await waitFor(() => {
            expect(searchInput.value).toBe('moon');
        });

        // The X button is an icon button with no text — find by its container
        const xButton = searchInput.parentElement.querySelector('button');
        expect(xButton).toBeInTheDocument();
        fireEvent.click(xButton);

        await waitFor(() => {
            expect(searchInput.value).toBe('');
        });
    });
});
