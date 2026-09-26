import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import ImageLightbox from './ImageLightbox';

vi.mock('../ProgressiveImage', () => ({
    default: ({ alt }) => <img data-testid="mock-image" alt={alt} />
}));

const img = (name) => ({ name, relative_path: `default_user/chat/2026/09/26/${name}`, metadata: {} });
const images = [img('a.png'), img('b.png'), img('c.png')];

describe('ImageLightbox fullscreen', () => {
    // jsdom implements neither half of the Fullscreen API, so both are stubbed
    // and `document.fullscreenElement` is made writable the way a real browser
    // makes it change.
    let requestFullscreen;
    let exitFullscreen;
    let originalFullscreenElement;

    beforeEach(() => {
        requestFullscreen = vi.fn().mockResolvedValue(undefined);
        exitFullscreen = vi.fn().mockResolvedValue(undefined);
        Element.prototype.requestFullscreen = requestFullscreen;
        document.exitFullscreen = exitFullscreen;
        originalFullscreenElement = Object.getOwnPropertyDescriptor(document, 'fullscreenElement');
        Object.defineProperty(document, 'fullscreenElement', { configurable: true, writable: true, value: null });
    });

    afterEach(() => {
        delete Element.prototype.requestFullscreen;
        delete document.exitFullscreen;
        if (originalFullscreenElement) {
            Object.defineProperty(document, 'fullscreenElement', originalFullscreenElement);
        }
    });

    const enterNativeFullscreen = (dialog) => {
        Object.defineProperty(document, 'fullscreenElement', { configurable: true, writable: true, value: dialog });
        fireEvent(document, new Event('fullscreenchange'));
    };

    const base = (props = {}) => (
        <ImageLightbox
            image={images[0]}
            images={images}
            currentIndex={0}
            onNavigate={() => {}}
            onClose={() => {}}
            {...props}
        />
    );

    it('offers both a focus toggle and a browser fullscreen toggle', () => {
        render(base());
        expect(screen.getByLabelText('Toggle focus mode')).toBeInTheDocument();
        expect(screen.getByLabelText('Toggle browser fullscreen')).toBeInTheDocument();
    });

    it('focus mode hides the details sidebar and restores it', () => {
        render(base());
        expect(screen.getByText('Details')).toBeInTheDocument();

        fireEvent.click(screen.getByLabelText('Toggle focus mode'));
        expect(screen.queryByText('Details')).not.toBeInTheDocument();
        expect(screen.getByLabelText('Toggle focus mode')).toHaveAttribute('aria-pressed', 'true');

        fireEvent.click(screen.getByLabelText('Toggle focus mode'));
        expect(screen.getByText('Details')).toBeInTheDocument();
    });

    it('keeps navigation working in focus mode', () => {
        const onNavigate = vi.fn();
        // Four images, so each of the three gestures below has somewhere to go:
        // at a 3-image list the final swipe would sit on the last index and
        // correctly refuse to advance.
        const four = [img('a.png'), img('b.png'), img('c.png'), img('d.png')];
        render(
            <ImageLightbox
                image={four[0]}
                images={four}
                currentIndex={0}
                onNavigate={onNavigate}
                onClose={() => {}}
            />
        );
        fireEvent.click(screen.getByLabelText('Toggle focus mode'));

        // Focus mode must not cost the user the thing they were here for.
        fireEvent.click(screen.getByLabelText('Next image'));
        expect(onNavigate).toHaveBeenLastCalledWith(1);

        fireEvent.keyDown(window, { key: 'ArrowRight' });
        expect(onNavigate).toHaveBeenLastCalledWith(2);

        const area = screen.getByTestId('lightbox-swipe-area');
        fireEvent.touchStart(area, { touches: [{ clientX: 200, clientY: 200 }] });
        fireEvent.touchEnd(area, { changedTouches: [{ clientX: 80, clientY: 205 }] });
        expect(onNavigate).toHaveBeenLastCalledWith(3);
    });

    it('requests browser fullscreen on the dialog element', () => {
        render(base());
        fireEvent.click(screen.getByLabelText('Toggle browser fullscreen'));
        expect(requestFullscreen).toHaveBeenCalledTimes(1);
    });

    it('reflects leaving fullscreen from outside the app', () => {
        render(base());
        const dialog = screen.getByRole('dialog', { name: 'Image lightbox' });
        enterNativeFullscreen(dialog);

        const toggle = screen.getByLabelText('Toggle browser fullscreen');
        expect(toggle).toHaveAttribute('aria-pressed', 'true');
        // F11, the browser's own Escape, or a tab switch can all drop out of
        // fullscreen, so the state is read from the document, not assumed.
        Object.defineProperty(document, 'fullscreenElement', { configurable: true, writable: true, value: null });
        fireEvent(document, new Event('fullscreenchange'));
        expect(toggle).toHaveAttribute('aria-pressed', 'false');
    });

    it('exits browser fullscreen when the toggle is pressed while fullscreen', () => {
        render(base());
        const dialog = screen.getByRole('dialog', { name: 'Image lightbox' });
        enterNativeFullscreen(dialog);

        fireEvent.click(screen.getByLabelText('Toggle browser fullscreen'));
        expect(exitFullscreen).toHaveBeenCalledTimes(1);
    });

    it('does not close the viewer on Escape while the browser owns the screen', () => {
        const onClose = vi.fn();
        render(base({ onClose }));
        const dialog = screen.getByRole('dialog', { name: 'Image lightbox' });
        enterNativeFullscreen(dialog);

        // The browser consumes Escape to leave fullscreen and never delivers
        // it, so the viewer must survive on the keypress that browsers do pass
        // through. A second Escape, once fullscreen is gone, closes it.
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).not.toHaveBeenCalled();

        Object.defineProperty(document, 'fullscreenElement', { configurable: true, writable: true, value: null });
        fireEvent(document, new Event('fullscreenchange'));
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('still closes from the close button while fullscreen', () => {
        const onClose = vi.fn();
        render(base({ onClose }));
        const dialog = screen.getByRole('dialog', { name: 'Image lightbox' });
        enterNativeFullscreen(dialog);

        // Only the Escape path is gated; the explicit close must not be.
        fireEvent.click(screen.getByLabelText('Close lightbox'));
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('closes on Escape when not in fullscreen', () => {
        const onClose = vi.fn();
        render(base({ onClose }));
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('leaves fullscreen when the viewer goes away', () => {
        const { unmount } = render(base());
        const dialog = screen.getByRole('dialog', { name: 'Image lightbox' });
        enterNativeFullscreen(dialog);

        unmount();
        // Otherwise the document stays fullscreen with nothing filling it.
        expect(exitFullscreen).toHaveBeenCalled();
    });

    it('omits the browser fullscreen button when the API is unavailable', () => {
        delete Element.prototype.requestFullscreen;
        render(base());
        // iPhone Safari: focus mode still has to be offered.
        expect(screen.queryByLabelText('Toggle browser fullscreen')).not.toBeInTheDocument();
        expect(screen.getByLabelText('Toggle focus mode')).toBeInTheDocument();
    });
});
