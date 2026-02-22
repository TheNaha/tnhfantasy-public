import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import EmptyState from './EmptyState';

// Mock Lucide icons to avoid rendering issues if any
vi.mock('lucide-react', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        // We can just use the actual icons or mock them if needed
    };
});

describe('EmptyState', () => {
    const renderWithRouter = (ui) => {
        return render(<MemoryRouter>{ui}</MemoryRouter>);
    };

    it('renders default gallery state', () => {
        renderWithRouter(<EmptyState />);
        expect(screen.getByText('No images yet')).toBeInTheDocument();
        expect(screen.getByText('Start creating amazing AI-generated images with your prompts')).toBeInTheDocument();
    });

    it('renders search state', () => {
        renderWithRouter(<EmptyState type="search" />);
        expect(screen.getByText('No results found')).toBeInTheDocument();
        expect(screen.getByText('We couldn\'t find any images matching your search. Try adjusting your filters or search terms.')).toBeInTheDocument();
    });

    it('renders custom title and description', () => {
        renderWithRouter(
            <EmptyState
                title="Custom Title"
                description="Custom Description"
            />
        );
        expect(screen.getByText('Custom Title')).toBeInTheDocument();
        expect(screen.getByText('Custom Description')).toBeInTheDocument();
    });

    it('calls onAction when primary button is clicked', () => {
        const handleAction = vi.fn();
        renderWithRouter(
            <EmptyState
                type="gallery"
                onAction={handleAction}
            />
        );

        // Button text defaults to "Generate Your First Image" for gallery
        fireEvent.click(screen.getByText('Generate Your First Image'));
        expect(handleAction).toHaveBeenCalledTimes(1);
    });

    it('calls onSecondary when secondary button is clicked', () => {
        const handleSecondary = vi.fn();
        renderWithRouter(
            <EmptyState
                type="gallery"
                onSecondary={handleSecondary}
            />
        );

        // Button text defaults to "Browse Models" for gallery
        fireEvent.click(screen.getByText('Browse Models'));
        expect(handleSecondary).toHaveBeenCalledTimes(1);
    });

    it('shows tutorial hint when enabled', () => {
        renderWithRouter(
            <EmptyState
                type="gallery"
                showTutorialHint={true}
            />
        );
        expect(screen.getByText(/Tip: Start simple!/)).toBeInTheDocument();
    });
});
