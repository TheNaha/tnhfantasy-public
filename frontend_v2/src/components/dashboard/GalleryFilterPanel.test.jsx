import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Only the vocabulary module is mocked, and it is spread rather than replaced:
// `useTagVocabulary` used to live in `hooks/useGallery` next to
// `FACET_DIMENSIONS`, which the panel still imports from there. A mock written to
// match the import instead of the module is what let a default import of a
// module with no default export pass every test and then fail the build.
const vocabularyMock = vi.hoisted(() => ({ entries: [] }));
vi.mock('../../hooks/useAssetTags', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        // The real hook takes an options object and returns the raw response; the
        // deleted copy in `useGallery.js` took a bare prefix string and `select`ed
        // the array out. A stub shaped like the old one would let a
        // `data?.tags` regression pass every test in this file.
        useTagVocabulary: ({ prefix } = {}) => ({
            data: { tags: prefix ? vocabularyMock.entries : [] },
            isLoading: false,
        }),
    };
});

import GalleryFilterPanel from './GalleryFilterPanel';

const FACETS = {
    lora: [
        { value: '123', count: 12, label: 'Detail Slider' },
        { value: '456', count: 4, label: 'Detail Tweaker' },
    ],
    tag: [
        { value: 'cyberpunk', count: 9 },
        { value: 'portrait', count: 3 },
    ],
    checkpoint: [
        { value: 'sdxl.safetensors', count: 20 },
    ],
};

function renderPanel(props = {}) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const onChange = vi.fn();
    const utils = render(
        <QueryClientProvider client={queryClient}>
            <GalleryFilterPanel facets={FACETS} filters={{}} onChange={onChange} {...props} />
        </QueryClientProvider>,
    );
    // Sections are COLLAPSED by default (see `FacetSection`), so a test that
    // wants to click a chip has to open the section first — which is also what a
    // user does, so the test now exercises the real path to the chip.
    if (props.expandSections !== false) {
        ['lora', 'tag', 'checkpoint'].forEach((dim) => {
            const header = document.querySelector(`[data-testid="facet-section-${dim}"]`);
            if (header && header.getAttribute('aria-expanded') === 'false') {
                fireEvent.click(header);
            }
        });
    }
    return { ...utils, onChange };
}

function chip(value) {
    return document.querySelector(`[data-testid="facet-chip-lora"][data-value="${value}"]`);
}

describe('GalleryFilterPanel', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
        vocabularyMock.entries = [];
    });

    afterEach(() => cleanup());

    it('collapses its sections by default, and opens only what is filtering', () => {
        // Three sections open at once is ~70 chips of LoRA names and counts
        // pushed into the gallery's own scroll area. The panel buries the images
        // it is supposed to be filtering.
        const { unmount } = renderPanel({ expandSections: false });

        ['lora', 'tag', 'checkpoint'].forEach((dim) => {
            const header = document.querySelector(`[data-testid="facet-section-${dim}"]`);
            expect(header, `${dim} header missing`).not.toBeNull();
            expect(header.getAttribute('aria-expanded'), `${dim} should start collapsed`).toBe('false');
        });
        expect(document.querySelector('[data-testid="facet-chip-lora"]')).toBeNull();
        unmount();

        // A filter applied from anywhere else — the date rail, a restored
        // session, a shared link — opens its own section rather than leaving a
        // live filter hidden behind a closed header.
        renderPanel({ expandSections: false, filters: { checkpoint: 'sdxl.safetensors' } });
        expect(
            document.querySelector('[data-testid="facet-section-checkpoint"]')
                .getAttribute('aria-expanded')
        ).toBe('true');
        // …and the ones that are not filtering stay shut.
        expect(
            document.querySelector('[data-testid="facet-section-lora"]')
                .getAttribute('aria-expanded')
        ).toBe('false');
    });

    it('a section the user collapsed stays collapsed even while it filters', () => {
        const { unmount } = renderPanel({ expandSections: false, filters: { lora: '123' } });
        const header = document.querySelector('[data-testid="facet-section-lora"]');
        expect(header.getAttribute('aria-expanded')).toBe('true');
        fireEvent.click(header);
        expect(header.getAttribute('aria-expanded')).toBe('false');
        unmount();
    });

    it('toggling a value adds it to the comma-separated string and keeps the existing ones', () => {
        const { onChange } = renderPanel({ filters: { lora: '999', search: 'portrait' } });

        fireEvent.click(screen.getByRole('button', { name: /Detail Slider/ }));

        expect(onChange).toHaveBeenCalledWith({ lora: '999,123', search: 'portrait' });
    });

    it('toggling a selected value off removes only that value', () => {
        const { onChange } = renderPanel({ filters: { lora: '123,456' } });

        fireEvent.click(screen.getByRole('button', { name: /Detail Slider/ }));

        expect(onChange).toHaveBeenCalledWith({ lora: '456' });
    });

    it('drops the key entirely when the last value is toggled off', () => {
        const { onChange } = renderPanel({ filters: { lora: '123', search: 'x' } });

        fireEvent.click(screen.getByRole('button', { name: /Detail Slider/ }));

        expect(onChange).toHaveBeenCalledWith({ search: 'x' });
        expect(onChange.mock.calls[0][0]).not.toHaveProperty('lora');
    });

    it('does not choke on an empty or malformed comma-separated string', () => {
        const { onChange } = renderPanel({ filters: { lora: ' , , ' } });

        fireEvent.click(screen.getByRole('button', { name: /Detail Slider/ }));

        expect(onChange).toHaveBeenCalledWith({ lora: '123' });
    });

    it('keeps a selected value visible when the counts do not contain it', () => {
        // The count for a dimension is computed with that dimension's own filter
        // removed, and `facet_limit` can cut a rare value off entirely.
        renderPanel({ facets: { ...FACETS, lora: [] }, filters: { lora: '777' } });

        const orphan = chip('777');
        expect(orphan).toBeInTheDocument();
        expect(orphan).toHaveAttribute('aria-pressed', 'true');
        expect(orphan).toHaveTextContent('—');
    });

    it('toggles a selected value that is missing from the counts back off', () => {
        const { onChange } = renderPanel({ facets: { ...FACETS, lora: [] }, filters: { lora: '777' } });

        fireEvent.click(chip('777'));

        expect(onChange).toHaveBeenCalledWith({});
    });

    it('marks selected chips as pressed and unselected ones as not', () => {
        renderPanel({ filters: { lora: '456' } });

        expect(chip('456')).toHaveAttribute('aria-pressed', 'true');
        expect(chip('123')).toHaveAttribute('aria-pressed', 'false');
    });

    it('shows how many values are selected on each dimension heading', () => {
        renderPanel({ filters: { lora: '123,456' } });

        expect(screen.getByTestId('facet-selected-lora')).toHaveTextContent('2 selected');
        expect(screen.queryByTestId('facet-selected-tag')).not.toBeInTheDocument();
    });

    describe('clear', () => {
        it('is absent when nothing is selected', () => {
            renderPanel({ filters: { search: 'still a search, not ours' } });

            expect(screen.queryByTestId('facet-clear')).not.toBeInTheDocument();
        });

        it('counts a date range as a selection', () => {
            renderPanel({ filters: { date_from: '2026-09-01T00:00:00Z' } });

            expect(screen.getByTestId('facet-clear')).toBeInTheDocument();
        });

        it('emits only the keys the panel owns when no onClear is given', () => {
            const { onChange } = renderPanel({
                filters: {
                    lora: '123',
                    tag: 'cyberpunk',
                    checkpoint: 'sdxl.safetensors',
                    date_from: '2026-09-01T00:00:00Z',
                    date_to: '2026-09-02T23:59:59.999999Z',
                    search: 'keep me',
                    sort: 'date_desc',
                },
            });

            fireEvent.click(screen.getByTestId('facet-clear'));

            expect(onChange).toHaveBeenCalledWith({ search: 'keep me', sort: 'date_desc' });
        });

        it('hands the reset to onClear when the host owns one', () => {
            const onClear = vi.fn();
            const { onChange } = renderPanel({ filters: { lora: '123' }, onClear });

            fireEvent.click(screen.getByTestId('facet-clear'));

            expect(onClear).toHaveBeenCalledTimes(1);
            expect(onChange).not.toHaveBeenCalled();
        });
    });

    it('collapses to a show-all toggle instead of a scroll region', () => {
        const many = Array.from({ length: 20 }, (_, i) => ({ value: `ck-${i}`, count: i }));
        renderPanel({ facets: { ...FACETS, checkpoint: many }, filters: {} });

        expect(screen.getAllByTestId('facet-chip-checkpoint')).toHaveLength(12);
        const more = screen.getByTestId('facet-checkpoint-more');
        expect(more).toHaveTextContent('Show all 20');

        fireEvent.click(more);

        expect(screen.getAllByTestId('facet-chip-checkpoint')).toHaveLength(20);
        expect(screen.getByTestId('facet-checkpoint-more')).toHaveTextContent('Show less');
    });

    it('reports the matched total, and says so when there is none', () => {
        const { unmount } = renderPanel({ totalMatched: 1 });
        expect(screen.getByTestId('facet-total')).toHaveTextContent('1 matching image');
        unmount();

        renderPanel({ totalMatched: undefined });
        expect(screen.getByTestId('facet-total')).toHaveTextContent('Matching total unavailable');
    });

    it('suggests tags from the vocabulary and toggles the suggestion', () => {
        vocabularyMock.entries = [{ tag: 'neon', count: 6 }];
        const { onChange } = renderPanel({ filters: {} });

        fireEvent.change(screen.getByTestId('facet-tag-input'), { target: { value: 'ne' } });
        fireEvent.click(screen.getByRole('button', { name: /neon/ }));

        expect(onChange).toHaveBeenCalledWith({ tag: 'neon' });
    });
});
