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
    useUpdateMemory: vi.fn(),
    useDeleteMemory: vi.fn(),
    useSearchMemories: vi.fn(),
    useReindexMemories: vi.fn(),
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
    useUpdateMemory,
    useDeleteMemory,
    useSearchMemories,
    useReindexMemories,
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
    const mockReindexMutate = vi.fn();
    beforeEach(() => {
        vi.clearAllMocks();

        useCharacterMemories.mockReturnValue({ data: mockMemories, isLoading: false });
        useCreateMemory.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
        useUpdateMemory.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
        useDeleteMemory.mockReturnValue({ mutateAsync: mockMutateAsync, isPending: false });
        useSearchMemories.mockReturnValue({ data: null, isLoading: false });
        useReindexMemories.mockReturnValue({ mutateAsync: mockReindexMutate, isPending: false });
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

    it('edits a memory with correct payload when saved', async () => {
        const updateMock = vi.fn().mockResolvedValue({});
        useUpdateMemory.mockReturnValue({ mutateAsync: updateMock, isPending: false });
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        const editButtons = screen.getAllByTitle('Edit memory');
        fireEvent.click(editButtons[0]);

        const editTextarea = screen.getByPlaceholderText('Memory content…');
        fireEvent.change(editTextarea, { target: { value: 'The hero was born under a red moon.' } });

        fireEvent.click(screen.getByText('Save Changes'));

        await waitFor(() => {
            expect(updateMock).toHaveBeenCalledWith({
                id: 'mem-1',
                characterId: 'char-1',
                content: 'The hero was born under a red moon.',
                importance: 8,
                tags: ['birth', 'omen'],
            });
        });

        // Edit form closes after save
        await waitFor(() => {
            expect(screen.queryByText('Save Changes')).not.toBeInTheDocument();
        });
    });

    it('cancels edit without saving', () => {
        const updateMock = vi.fn();
        useUpdateMemory.mockReturnValue({ mutateAsync: updateMock, isPending: false });
        const { wrapper } = createWrapper();
        render(<MemoriesPanel characterId="char-1" />, { wrapper });

        fireEvent.click(screen.getAllByTitle('Edit memory')[0]);
        expect(screen.getByText('Editing memory')).toBeInTheDocument();
        fireEvent.click(screen.getByTitle('Cancel edit'));
        expect(screen.queryByText('Editing memory')).not.toBeInTheDocument();
        expect(updateMock).not.toHaveBeenCalled();
    });

    /**
     * A failed fetch is not an empty memory list.
     *
     * Both queries destructured only `data`/`isLoading`, so a rejected request
     * left `memories` at its `= []` default and rendered "No memories yet / Add
     * the first memory for this character" for a character that already had
     * two. Found by the widened `queryErrorInvariants` scan (2026-10-04), which
     * now walks `src/**` instead of `src/pages/`.
     */
    describe('a failed fetch is a failure, not an empty memory list', () => {
        it('states the failure and never says the character has no memories', () => {
            useCharacterMemories.mockReturnValue({
                data: [], isLoading: false, isError: true,
                error: new Error('503 Service Unavailable'), refetch: vi.fn(),
            });
            const { wrapper } = createWrapper();
            render(<MemoriesPanel characterId="char-1" />, { wrapper });

            const alert = screen.getByRole('alert');
            expect(alert).toHaveTextContent(/could not load your memories/i);
            expect(alert).toHaveTextContent(/503 Service Unavailable/);
            expect(screen.queryByText('No memories yet')).toBeNull();
        });

        it('offers a retry wired to the memories refetch', () => {
            const refetch = vi.fn();
            useCharacterMemories.mockReturnValue({
                data: [], isLoading: false, isError: true,
                error: new Error('boom'), refetch,
            });
            const { wrapper } = createWrapper();
            render(<MemoriesPanel characterId="char-1" />, { wrapper });

            fireEvent.click(screen.getByRole('button', { name: /try again/i }));
            expect(refetch).toHaveBeenCalledTimes(1);
        });

        it('reports a failed SEARCH separately from a failed list', () => {
            // Two queries, two failure modes. "No matches found" for a search
            // that never ran is the same class of lie.
            useSearchMemories.mockReturnValue({
                data: null, isFetching: false, isError: true,
                error: new Error('search failed'), refetch: vi.fn(),
            });
            const { wrapper } = createWrapper();
            render(<MemoriesPanel characterId="char-1" />, { wrapper });

            expect(screen.getByRole('alert')).toHaveTextContent(/could not load your memory matches/i);
        });

        it('still says "No memories yet" when the fetch genuinely succeeded', () => {
            useCharacterMemories.mockReturnValue({
                data: [], isLoading: false, isError: false, error: null, refetch: vi.fn(),
            });
            const { wrapper } = createWrapper();
            render(<MemoriesPanel characterId="char-1" />, { wrapper });

            expect(screen.getByText('No memories yet')).toBeTruthy();
            expect(screen.queryByRole('alert')).toBeNull();
        });

        it('triggers reindex mutation when Reindex button is clicked', () => {
            const { wrapper } = createWrapper();
            render(<MemoriesPanel characterId="char-1" />, { wrapper });

            const reindexBtn = screen.getByRole('button', { name: /reindex/i });
            expect(reindexBtn).toBeInTheDocument();
            fireEvent.click(reindexBtn);
            expect(mockReindexMutate).toHaveBeenCalledTimes(1);
        });
    });
});
