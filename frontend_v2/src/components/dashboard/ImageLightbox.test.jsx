import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ImageLightbox from './ImageLightbox';
// `ImageLightbox` renders `AssetTagEditor`, which reads and writes tags through
// react-query, so the viewer now needs a QueryClient it did not need before.
// Only the provider is added; no assertion in these files changed.

function render(ui) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    return rtlRender(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}


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

    it('moves to the next image on a left swipe and previous on a right swipe', () => {
        const onNavigate = vi.fn();
        render(
            <ImageLightbox
                image={mockImage}
                images={mockImages}
                currentIndex={1}
                onNavigate={onNavigate}
                onClose={() => {}}
            />
        );

        const area = screen.getByTestId('lightbox-swipe-area');
        fireEvent.touchStart(area, { touches: [{ clientX: 200, clientY: 200 }] });
        fireEvent.touchEnd(area, { changedTouches: [{ clientX: 80, clientY: 205 }] });
        expect(onNavigate).toHaveBeenLastCalledWith(2);

        fireEvent.touchStart(area, { touches: [{ clientX: 80, clientY: 200 }] });
        fireEvent.touchEnd(area, { changedTouches: [{ clientX: 200, clientY: 200 }] });
        expect(onNavigate).toHaveBeenLastCalledWith(1);
    });

    it('renders elevated Reuse Parameters and Copy buttons when metadata is present', () => {
        const onReuse = vi.fn();
        const metadata = {
            prompt: 'masterpiece, high quality illustration',
            negativePrompt: 'blurry, low quality',
            seed: 12345,
            steps: 20,
            cfg: 7,
        };

        render(
            <ImageLightbox
                image={mockImage}
                images={mockImages}
                currentIndex={0}
                metadata={metadata}
                onClose={() => {}}
                onDelete={() => {}}
                onReuseParameters={onReuse}
            />
        );

        const reuseBtn = screen.getByRole('button', { name: 'Reuse parameters from this image' });
        expect(reuseBtn).toBeInTheDocument();
        fireEvent.click(reuseBtn);
        expect(onReuse).toHaveBeenCalledTimes(1);

        const copyPromptBtn = screen.getByRole('button', { name: 'Copy prompt' });
        expect(copyPromptBtn).toBeInTheDocument();
    });

    it('renders elevated Generation Telemetry when timings are present', () => {
        const metadata = {
            prompt: 'masterpiece, high quality illustration',
            timings: {
                model_load_seconds: 1.1,
                sampling_seconds: 2.2,
                transfer_seconds: 0.5,
                total_backend_seconds: 3.8,
            },
        };

        render(
            <ImageLightbox
                image={mockImage}
                images={mockImages}
                currentIndex={0}
                metadata={metadata}
                onClose={() => {}}
                onDelete={() => {}}
            />
        );

        expect(screen.getByTestId('generation-telemetry')).toBeInTheDocument();
        expect(screen.getAllByText('3.80s').length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText('1.10s')).toBeInTheDocument();
        expect(screen.getByText('2.20s')).toBeInTheDocument();
    });

    it('fetches and renders telemetry from linked job when metadata.job_id is present', async () => {
        const { jobsApi } = await import('../../api/jobs');
        vi.spyOn(jobsApi, 'get').mockResolvedValue({
            id: 'job-xyz-999',
            provider_id: 'colab-one',
            timings: {
                model_load_seconds: 4.5,
                sampling_seconds: 12.0,
                total_backend_seconds: 16.5,
            },
        });

        render(
            <ImageLightbox
                image={mockImage}
                images={mockImages}
                currentIndex={0}
                metadata={{ job_id: 'job-xyz-999', steps: 25 }}
                onClose={() => {}}
                onDelete={() => {}}
            />
        );

        expect(await screen.findByTestId('generation-telemetry')).toBeInTheDocument();
        expect(await screen.findByText('12.00s')).toBeInTheDocument();
        expect(screen.getByText(/25 steps @/)).toBeInTheDocument();
        expect(screen.getAllByText('colab-one').length).toBeGreaterThanOrEqual(1);
    });
});
