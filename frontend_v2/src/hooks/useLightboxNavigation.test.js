import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useLightboxNavigation, flattenGalleryImages, identityOf } from './useLightboxNavigation';

const img = (name, extra = {}) => ({
    type: 'image',
    name,
    relative_path: `default_user/chat/2026/09/26/${name}`,
    ...extra,
});

const groups = (items) => [['2026-09-26', items]];

describe('flattenGalleryImages', () => {
    it('keeps visual order across groups', () => {
        const flat = flattenGalleryImages([
            ['2026-09-26', [img('a.png'), img('b.png')]],
            ['2026-09-25', [img('c.png')]],
        ]);
        expect(flat.map(identityOf)).toEqual([
            'default_user/chat/2026/09/26/a.png',
            'default_user/chat/2026/09/26/b.png',
            'default_user/chat/2026/09/26/c.png',
        ]);
    });

    it('expands image groups in place and drops job entries', () => {
        const flat = flattenGalleryImages(groups([
            img('a.png'),
            { type: 'imageGroup', id: 'group-1', images: [img('x.png'), img('y.png')] },
            { type: 'job', id: 'job-1' },
            img('b.png'),
        ]));
        expect(flat.map((i) => i.name)).toEqual(['a.png', 'x.png', 'y.png', 'b.png']);
    });

    it('tolerates malformed input', () => {
        expect(flattenGalleryImages(undefined)).toEqual([]);
        expect(flattenGalleryImages(null)).toEqual([]);
        expect(flattenGalleryImages([['k', null]])).toEqual([]);
        expect(flattenGalleryImages([['k', [{ type: 'imageGroup' }]]])).toEqual([]);
    });
});

describe('identityOf', () => {
    it('prefers the workspace-qualified path over the basename', () => {
        // Two assets in different workspaces can share a basename; only
        // relative_path tells them apart.
        const a = img('seed.png');
        const b = { name: 'seed.png', relative_path: 'other_ws/chat/seed.png' };
        expect(identityOf(a)).not.toBe(identityOf(b));
    });

    it('falls back to name, then empty', () => {
        expect(identityOf({ name: 'x.png' })).toBe('x.png');
        expect(identityOf(null)).toBe('');
    });
});

describe('useLightboxNavigation', () => {
    const setup = (overrides = {}) => renderHook(() => useLightboxNavigation({
        sortedGroupedEntries: groups([img('a.png'), img('b.png'), img('c.png')]),
        selectedImage: img('b.png'),
        ...overrides,
    }));

    it('derives the current index from identity, not position', () => {
        const { result } = setup();
        expect(result.current.currentIndex).toBe(1);
        expect(result.current.canGoPrev).toBe(true);
        expect(result.current.canGoNext).toBe(true);
    });

    it('follows the selected image when the list shifts', () => {
        // Simulates the user scrolling the grid to pull in another page while
        // the viewer is open. A stored index would now point at another image.
        const { result, rerender } = renderHook(({ entries }) => useLightboxNavigation({
            sortedGroupedEntries: entries,
            selectedImage: img('b.png'),
        }), { initialProps: { entries: groups([img('a.png'), img('b.png')]) } });

        expect(result.current.currentIndex).toBe(1);
        rerender({ entries: groups([img('z.png'), img('a.png'), img('b.png')]) });
        expect(result.current.currentIndex).toBe(2);
        expect(result.current.images[2].name).toBe('b.png');
    });

    it('degrades to a single-item list when the selected image is not listed', () => {
        // e.g. a filter changed underneath an open viewer. It must show the
        // image the user opened, not whatever sits at index 0.
        const { result } = setup({ selectedImage: img('not-in-list.png') });
        expect(result.current.isListed).toBe(false);
        expect(result.current.currentIndex).toBe(0);
        expect(result.current.images).toHaveLength(1);
        expect(result.current.images[0].name).toBe('not-in-list.png');
        expect(result.current.canGoPrev).toBe(false);
        expect(result.current.canGoNext).toBe(false);
    });

    it('treats the end of the loaded prefix as navigable while more pages exist', () => {
        const { result } = setup({ selectedImage: img('c.png'), hasMore: true, onLoadMore: () => {} });
        expect(result.current.currentIndex).toBe(2);
        expect(result.current.canGoNext).toBe(true);
    });

    it('does not report next at the true end', () => {
        const { result } = setup({ selectedImage: img('c.png'), hasMore: false });
        expect(result.current.canGoNext).toBe(false);
    });

    it('resolveTarget returns the image at the index, carrying job context', () => {
        const { result } = setup({
            selectedImage: { ...img('b.png'), associatedJob: { id: 'j1' } },
        });
        const target = result.current.resolveTarget(2);
        expect(target.name).toBe('c.png');
        expect(target.associatedJob).toEqual({ id: 'j1' });
    });

    it('resolveTarget returns null for an out-of-range index', () => {
        const { result } = setup();
        expect(result.current.resolveTarget(99)).toBeNull();
    });
});
