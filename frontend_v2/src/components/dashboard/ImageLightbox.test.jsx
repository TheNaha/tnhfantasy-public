import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import ImageLightbox from './ImageLightbox';

// Mock ProgressiveImage to simplify testing
vi.mock('../ProgressiveImage', () => ({
    default: () => <img data-testid="mock-image" />
}));

describe('ImageLightbox', () => {
    const mockImage = {
        name: 'test.png',
        size: 1024,
        blurhash: '...',
        metadata: {}
    };

    const mockImages = [
        mockImage,
        { ...mockImage, name: 'test2.png' },
        { ...mockImage, name: 'test3.png' }
    ];

    it('has accessible buttons', () => {
        render(
            <ImageLightbox
                image={mockImage}
                images={mockImages}
                currentIndex={1}
                onClose={() => {}}
                onDelete={() => {}}
            />
        );

        // Verify close button aria-label
        const closeBtn = screen.getByLabelText('Close lightbox');
        expect(closeBtn).toBeInTheDocument();
        // Check for outline/focus classes
        expect(closeBtn.className).toContain('outline-none');
        expect(closeBtn.className).toContain('focus-visible:ring-2');

        // Verify previous button aria-label
        const prevBtn = screen.getByLabelText('Previous image');
        expect(prevBtn).toBeInTheDocument();
        expect(prevBtn.className).toContain('outline-none');
        expect(prevBtn.className).toContain('focus-visible:ring-2');

        // Verify next button aria-label
        const nextBtn = screen.getByLabelText('Next image');
        expect(nextBtn).toBeInTheDocument();
        expect(nextBtn.className).toContain('outline-none');
        expect(nextBtn.className).toContain('focus-visible:ring-2');

        // Verify dot indicators
        const dots = screen.getAllByRole('button').filter(b => b.getAttribute('aria-label')?.startsWith('Go to image'));
        expect(dots).toHaveLength(3);

        const activeDot = dots[1];
        expect(activeDot).toHaveAttribute('aria-pressed', 'true');
        expect(activeDot.className).toContain('focus-visible:ring-2');
    });
});
