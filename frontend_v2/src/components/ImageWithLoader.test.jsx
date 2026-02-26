import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import ImageWithLoader from './ImageWithLoader';

// Mock lucide icons
vi.mock('lucide-react', () => ({
    Loader2: ({ className }) => <div data-testid="loader" className={className} />,
    ImageIcon: ({ className }) => <div data-testid="error-icon" className={className} />
}));

describe('ImageWithLoader', () => {
    it('renders loading state initially', () => {
        render(<ImageWithLoader src="test.jpg" alt="test image" />);
        expect(screen.getByTestId('loader')).toBeInTheDocument();
        const img = screen.getByRole('img');
        expect(img).toHaveClass('opacity-0');
    });

    it('shows image when loaded', () => {
        render(<ImageWithLoader src="test.jpg" alt="test image" />);
        const img = screen.getByRole('img');

        fireEvent.load(img);

        expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
        expect(img).toHaveClass('opacity-100');
    });

    it('shows error state when load fails', () => {
        render(<ImageWithLoader src="test.jpg" alt="test image" />);
        const img = screen.getByRole('img');

        fireEvent.error(img);

        expect(screen.getByTestId('error-icon')).toBeInTheDocument();
        expect(screen.getByText('Failed to load')).toBeInTheDocument();
        expect(screen.queryByTestId('loader')).not.toBeInTheDocument();
    });

    it('calls onLoad callback', () => {
        const onLoad = vi.fn();
        render(<ImageWithLoader src="test.jpg" onLoad={onLoad} />);
        const img = screen.getByRole('img');

        fireEvent.load(img);

        expect(onLoad).toHaveBeenCalled();
    });

    it('calls onError callback', () => {
        const onError = vi.fn();
        render(<ImageWithLoader src="test.jpg" onError={onError} />);
        const img = screen.getByRole('img');

        fireEvent.error(img);

        expect(onError).toHaveBeenCalled();
    });
});
