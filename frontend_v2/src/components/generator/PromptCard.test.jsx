import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import PromptCard from './PromptCard';

// Mock Lucide icons
vi.mock('lucide-react', () => ({
    Star: () => <span data-testid="icon-star" />,
    Trash2: () => <span data-testid="icon-trash" />,
    Copy: () => <span data-testid="icon-copy" />,
    Check: () => <span data-testid="icon-check" />,
    Edit2: () => <span data-testid="icon-edit" />,
    TrendingUp: () => <span data-testid="icon-trending" />
}));

describe('PromptCard', () => {
    const mockPrompt = {
        id: '1',
        name: 'Test Prompt',
        description: 'A test description',
        text: 'This is the prompt text',
        category: 'Testing',
        tags: ['tag1', 'tag2'],
        createdAt: new Date().toISOString(),
        favorite: false,
        usageCount: 5
    };

    const mockHandlers = {
        onUse: vi.fn(),
        onEdit: vi.fn(),
        onDelete: vi.fn(),
        onToggleFavorite: vi.fn()
    };

    beforeEach(() => {
        // Mock clipboard API
        Object.assign(navigator, {
            clipboard: {
                writeText: vi.fn().mockImplementation(() => Promise.resolve()),
            },
        });
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.clearAllMocks();
        vi.useRealTimers();
    });

    it('renders prompt details correctly', () => {
        render(<PromptCard prompt={mockPrompt} {...mockHandlers} />);

        expect(screen.getByText('Test Prompt')).toBeInTheDocument();
        expect(screen.getByText('A test description')).toBeInTheDocument();
        expect(screen.getByText('This is the prompt text')).toBeInTheDocument();
        expect(screen.getByText('Testing')).toBeInTheDocument();
        expect(screen.getByText('tag1')).toBeInTheDocument();
        expect(screen.getByText('tag2')).toBeInTheDocument();
    });

    it('calls onUse when "Use Prompt" is clicked', () => {
        render(<PromptCard prompt={mockPrompt} {...mockHandlers} />);

        fireEvent.click(screen.getByText('Use Prompt'));
        expect(mockHandlers.onUse).toHaveBeenCalledWith(mockPrompt);
    });

    it('calls onToggleFavorite when favorite button is clicked', () => {
        render(<PromptCard prompt={mockPrompt} {...mockHandlers} />);

        const favButton = screen.getByRole('button', { name: /add to favorites/i });
        fireEvent.click(favButton);
        expect(mockHandlers.onToggleFavorite).toHaveBeenCalledWith('1');
    });

    it('calls onEdit when edit button is clicked', () => {
        render(<PromptCard prompt={mockPrompt} {...mockHandlers} />);

        const editButton = screen.getByRole('button', { name: /edit prompt/i });
        fireEvent.click(editButton);
        expect(mockHandlers.onEdit).toHaveBeenCalledWith(mockPrompt);
    });

    it('calls onDelete when delete button is clicked', () => {
        render(<PromptCard prompt={mockPrompt} {...mockHandlers} />);

        const deleteButton = screen.getByRole('button', { name: /delete prompt/i });
        fireEvent.click(deleteButton);
        expect(mockHandlers.onDelete).toHaveBeenCalledWith('1');
    });

    it('copies text and shows visual feedback', async () => {
        render(<PromptCard prompt={mockPrompt} {...mockHandlers} />);

        const copyButton = screen.getByRole('button', { name: /copy to clipboard/i });

        // Initial state
        expect(screen.getByTestId('icon-copy')).toBeInTheDocument();
        expect(screen.queryByTestId('icon-check')).not.toBeInTheDocument();

        // Click copy
        await act(async () => {
             fireEvent.click(copyButton);
        });

        expect(navigator.clipboard.writeText).toHaveBeenCalledWith('This is the prompt text');

        // Verify "Copied" state immediately (no waitFor needed for sync state update, but good practice)
        expect(screen.getByTestId('icon-check')).toBeInTheDocument();
        expect(screen.queryByTestId('icon-copy')).not.toBeInTheDocument();
        // Check for the aria-label change
        expect(screen.getByRole('button', { name: /copied/i })).toBeInTheDocument();

        // Check green class
        expect(screen.getByRole('button', { name: /copied/i })).toHaveClass('text-green-400');

        // Fast-forward timer to reset
        act(() => {
            vi.advanceTimersByTime(2000);
        });

        // Verify reset state
        expect(screen.getByTestId('icon-copy')).toBeInTheDocument();
        expect(screen.queryByTestId('icon-check')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: /copy to clipboard/i })).toBeInTheDocument();
    });
});
