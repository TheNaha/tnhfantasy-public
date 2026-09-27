import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const datesMock = vi.hoisted(() => ({
    data: { days: [], total: 0, firstDay: null, lastDay: null },
    isLoading: false,
}));
// Spread, not replaced: the real module is what the rail is written against, and
// a mock shaped to the import hides a renamed export instead of failing on it.
vi.mock('../../hooks/useGallery', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useAssetDateHistogram: () => datesMock };
});

import GalleryDateRail from './GalleryDateRail';

function histogram(days) {
    datesMock.data = {
        days,
        total: days.reduce((n, d) => n + d.count, 0),
        firstDay: days[0]?.day ?? null,
        lastDay: days[days.length - 1]?.day ?? null,
    };
    datesMock.isLoading = false;
}

function consecutiveDays(count, start = '2026-01-01') {
    const first = Date.parse(`${start}T00:00:00Z`);
    return Array.from({ length: count }, (_, i) => ({
        day: new Date(first + i * 86_400_000).toISOString().slice(0, 10),
        count: 1,
    }));
}

function renderRail(props = {}) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const onChange = vi.fn();
    const utils = render(
        <QueryClientProvider client={queryClient}>
            <GalleryDateRail filters={{}} onChange={onChange} {...props} />
        </QueryClientProvider>,
    );
    return { ...utils, onChange };
}

const DAY_END = '2026-09-27T23:59:59.999999Z';

describe('GalleryDateRail', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
        histogram([]);
    });

    afterEach(() => cleanup());

    it('says so when the library is empty instead of rendering an empty rail', () => {
        renderRail();

        expect(screen.getByTestId('date-rail-empty')).toBeInTheDocument();
        expect(screen.queryByTestId('date-rail-bars')).not.toBeInTheDocument();
    });

    it('renders a loading state', () => {
        datesMock.isLoading = true;
        renderRail();

        expect(screen.getByTestId('date-rail-loading')).toBeInTheDocument();
        expect(screen.queryByTestId('date-rail-bars')).not.toBeInTheDocument();
    });

    it('renders a single day as one column', () => {
        histogram([{ day: '2026-09-27', count: 4 }]);
        renderRail();

        expect(screen.getAllByTestId('date-rail-day')).toHaveLength(1);
        expect(screen.queryByTestId('date-rail-aggregate')).not.toBeInTheDocument();
    });

    it('clicking a day sets UTC day bounds', () => {
        histogram([
            { day: '2026-09-26', count: 2 },
            { day: '2026-09-27', count: 12 },
        ]);
        const { onChange } = renderRail({ filters: { search: 'keep' } });

        fireEvent.click(screen.getByRole('button', { name: '2026-09-27, 12 images' }));

        expect(onChange).toHaveBeenCalledWith({
            search: 'keep',
            date_from: '2026-09-27T00:00:00Z',
            date_to: DAY_END,
        });
    });

    it('clicking the already-selected day clears the range', () => {
        histogram([{ day: '2026-09-27', count: 12 }]);
        const { onChange } = renderRail({
            filters: {
                date_from: '2026-09-27T00:00:00Z',
                date_to: DAY_END,
                search: 'keep',
            },
        });

        fireEvent.click(screen.getByRole('button', { name: '2026-09-27, 12 images' }));

        expect(onChange).toHaveBeenCalledWith({ search: 'keep' });
    });

    it('marks the selected day and shows the range with a clear control', () => {
        histogram([{ day: '2026-09-27', count: 12 }]);
        renderRail({ filters: { date_from: '2026-09-27T00:00:00Z', date_to: DAY_END } });

        expect(screen.getByRole('button', { name: '2026-09-27, 12 images' })).toHaveAttribute('aria-pressed', 'true');
        expect(screen.getByTestId('date-rail-range')).not.toHaveTextContent('Whole library');
        expect(screen.getByTestId('date-rail-clear')).toBeInTheDocument();
    });

    it('clears the range from the header control', () => {
        histogram([{ day: '2026-09-27', count: 12 }]);
        const { onChange } = renderRail({
            filters: { date_from: '2026-09-27T00:00:00Z', date_to: DAY_END },
        });

        fireEvent.click(screen.getByTestId('date-rail-clear'));

        expect(onChange).toHaveBeenCalledWith({});
    });

    it('buckets a multi-year span into a bounded number of columns and says they are aggregates', () => {
        histogram(consecutiveDays(900, '2020-01-01'));
        renderRail();

        const columns = screen.getAllByTestId('date-rail-aggregate');
        expect(columns).toHaveLength(48);
        expect(columns.length).toBeLessThan(900);
        expect(screen.getByTestId('date-rail-caption')).toHaveTextContent('aggregated');
        expect(columns[0].getAttribute('aria-label')).toMatch(/\(aggregated\)/);
    });

    it('an aggregated column selects the span of days it covers, in UTC', () => {
        histogram(consecutiveDays(900, '2020-01-01'));
        const { onChange } = renderRail();

        const first = screen.getAllByTestId('date-rail-aggregate')[0];
        const to = first.getAttribute('data-to');
        fireEvent.click(first);

        expect(onChange).toHaveBeenCalledWith({
            date_from: `${first.getAttribute('data-day')}T00:00:00Z`,
            date_to: `${to}T23:59:59.999999Z`,
        });
    });

    it('ignores unusable day rows rather than rendering a broken column', () => {
        histogram([
            { day: 'not-a-day', count: 5 },
            { day: '2026-09-27', count: 1 },
        ]);
        renderRail();

        expect(screen.getAllByTestId('date-rail-day')).toHaveLength(1);
    });
});
