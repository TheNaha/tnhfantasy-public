import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { useLightboxNavigation } from './useLightboxNavigation';

/**
 * The session view's groups hold SESSIONS, one pseudo-item each — not images.
 * So the gallery flattener yields nothing, every session image is "unlisted", and
 * the lightbox showed `1 / 1+` with no way to swipe, in a view whose whole point
 * is browsing a group of images together.
 *
 * The override list is what fixes it, and the important part is the second
 * behaviour below: the override must not hijack a gallery image.
 */
function renderNav(props) {
    const wrapper = ({ children }) => (
        <QueryClientProvider client={new QueryClient()}>
            {children}
        </QueryClientProvider>
    );
    return renderHook(() => useLightboxNavigation(props), { wrapper });
}

const sessionGroups = [
    ['session-a', [{ type: 'session', id: 'session-a', sessionId: 'a', name: 'A' }]],
    ['session-b', [{ type: 'session', id: 'session-b', sessionId: 'b', name: 'B' }]],
];

const groupImages = [
    { relative_path: 'a.png', name: 'a.png', type: 'image' },
    { relative_path: 'b.png', name: 'b.png', type: 'image' },
    { relative_path: 'c.png', name: 'c.png', type: 'image' },
];

describe('useLightboxNavigation in session view', () => {
    it('navigates within the session group the image was opened from', () => {
        const { result } = renderNav({
            sortedGroupedEntries: sessionGroups,
            selectedImage: groupImages[1],
            images: groupImages,
        });

        expect(result.current.images).toHaveLength(3);
        expect(result.current.currentIndex).toBe(1);
        expect(result.current.canGoPrev).toBe(true);
        expect(result.current.canGoNext).toBe(true);
        // And it moves to a real sibling, not just a number.
        expect(result.current.resolveTarget(2)?.name).toBe('c.png');
        expect(result.current.resolveTarget(0)?.name).toBe('a.png');
    });

    it('degrades to the gallery list when the selected image is not in the override', () => {
        // A gallery image must not start navigating an unrelated session, so the
        // override is ignored unless the selected image is actually in it.
        const galleryGroups = [[0, [{ relative_path: 'g.png', type: 'image' }]]];
        const { result } = renderNav({
            sortedGroupedEntries: galleryGroups,
            selectedImage: { relative_path: 'g.png', type: 'image' },
            images: groupImages,
        });

        expect(result.current.images).toHaveLength(1);
        expect(result.current.canGoNext).toBe(false);
    });

    it('reports no navigation at all for a session image before the fix', () => {
        // Pinned so the regression is visible: with session groups and no
        // override, the selected image is unlisted and the view collapses to one.
        const { result } = renderNav({
            sortedGroupedEntries: sessionGroups,
            selectedImage: groupImages[0],
        });

        expect(result.current.isListed).toBe(false);
        expect(result.current.images).toHaveLength(1);
    });
});
