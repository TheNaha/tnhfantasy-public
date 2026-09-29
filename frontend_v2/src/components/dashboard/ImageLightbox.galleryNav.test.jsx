import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render as rtlRender, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ImageLightbox from './ImageLightbox';
// `ImageLightbox` renders `AssetTagEditor`, which reads and writes tags through
// react-query, so the viewer now needs a QueryClient it did not need before.
// Only the provider is added; no assertion in these files changed.

function render(ui) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const result = rtlRender(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
    // Re-wrapped so a `rerender` keeps the same QueryClient; rerendering a bare
    // element would drop the provider and the tags query would have no client.
    const { rerender: rawRerender } = result;
    result.rerender = (next) => rawRerender(
        <QueryClientProvider client={queryClient}>{next}</QueryClientProvider>,
    );
    return result;
}


vi.mock('../ProgressiveImage', () => ({
    default: () => <img data-testid="mock-image" />
}));

describe('ImageLightbox gallery navigation', () => {
    const img = (name) => ({ name, relative_path: `default_user/chat/2026/09/26/${name}`, metadata: {} });

    it('stops at the first image instead of wrapping', () => {
        const onNavigate = vi.fn();
        render(<ImageLightbox image={img('a.png')} images={[img('a.png'), img('b.png')]} currentIndex={0} onNavigate={onNavigate} onClose={() => {}} />);

        fireEvent.click(screen.getByLabelText('Previous image'));
        // Old behaviour wrapped to the last image, which on a long gallery
        // throws the user to the far end of an unrelated section.
        expect(onNavigate).not.toHaveBeenCalled();
        expect(screen.getByLabelText('Previous image')).toBeDisabled();
    });

    it('stops at the last image when there are no more pages', () => {
        const onNavigate = vi.fn();
        render(<ImageLightbox image={img('a.png')} images={[img('a.png'), img('b.png')]} currentIndex={1} onNavigate={onNavigate} onClose={() => {}} />);

        fireEvent.click(screen.getByLabelText('Next image'));
        expect(onNavigate).not.toHaveBeenCalled();
        expect(screen.getByLabelText('Next image')).toBeDisabled();
    });

    it('navigates with arrow keys and does not wrap', () => {
        const onNavigate = vi.fn();
        render(<ImageLightbox image={img('a.png')} images={[img('a.png'), img('b.png'), img('c.png')]} currentIndex={1} onNavigate={onNavigate} onClose={() => {}} />);

        fireEvent.keyDown(window, { key: 'ArrowRight' });
        expect(onNavigate).toHaveBeenLastCalledWith(2);

        // At the end, ArrowRight must not jump back to 0.
        fireEvent.keyDown(window, { key: 'ArrowRight' });
        expect(onNavigate).toHaveBeenLastCalledWith(2);
        expect(onNavigate).not.toHaveBeenCalledWith(0);
    });

    it('offers navigation for a single loaded image when more pages exist', () => {
        render(<ImageLightbox image={img('a.png')} images={[img('a.png')]} currentIndex={0} onClose={() => {}} hasMore onLoadMore={() => {}} />);

        // The whole feature used to be gated on images.length > 1, so a
        // gallery with one page loaded showed no arrows at all.
        expect(screen.getByLabelText('Next image')).toBeInTheDocument();
        expect(screen.getByLabelText('Previous image')).toBeDisabled();
    });

    it('requests the next page when next walks off the end of the loaded prefix', () => {
        const onLoadMore = vi.fn();
        const onNavigate = vi.fn();
        const { rerender } = render(
            <ImageLightbox image={img('a.png')} images={[img('a.png')]} currentIndex={0} onNavigate={onNavigate} onClose={() => {}} hasMore onLoadMore={onLoadMore} />
        );

        fireEvent.click(screen.getByLabelText('Next image'));
        expect(onLoadMore).toHaveBeenCalledTimes(1);
        // Must not advance past the end before the page actually arrives, or the
        // cursor would point at an image that does not exist yet.
        expect(onNavigate).not.toHaveBeenCalled();

        // Page lands: the pending advance is consumed and the cursor moves on.
        rerender(
            <ImageLightbox image={img('a.png')} images={[img('a.png'), img('b.png')]} currentIndex={0} onNavigate={onNavigate} onClose={() => {}} hasMore onLoadMore={onLoadMore} />
        );
        expect(onNavigate).toHaveBeenCalledWith(1);
    });

    it('does not request more while a page is already loading', () => {
        const onLoadMore = vi.fn();
        render(
            <ImageLightbox image={img('a.png')} images={[img('a.png')]} currentIndex={0} onClose={() => {}} hasMore onLoadMore={onLoadMore} isLoadingMore />
        );

        expect(screen.getByLabelText('Next image')).toBeDisabled();
        fireEvent.click(screen.getByLabelText('Next image'));
        expect(onLoadMore).not.toHaveBeenCalled();
    });

    it('caps the dot indicators and admits the count is a prefix', () => {
        const many = Array.from({ length: 40 }, (_, i) => img(`i${i}.png`));
        render(<ImageLightbox image={many[0]} images={many} currentIndex={0} onClose={() => {}} hasMore />);

        // One dot per image is fine for a job batch, absurd for 16k images.
        expect(screen.queryByLabelText('Go to image 1')).not.toBeInTheDocument();
        expect(screen.getByText('1 / 40+')).toBeInTheDocument();
    });

    it('shows an exact count once the gallery is fully loaded', () => {
        const images = [img('a.png'), img('b.png')];
        render(<ImageLightbox image={images[0]} images={images} currentIndex={0} onClose={() => {}} />);

        expect(screen.getByText('1 / 2')).toBeInTheDocument();
    });

    it('shows no navigation for a lone image with nothing more to load', () => {
        render(<ImageLightbox image={img('a.png')} images={[img('a.png')]} currentIndex={0} onClose={() => {}} />);

        expect(screen.queryByLabelText('Next image')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('Previous image')).not.toBeInTheDocument();
    });
});
