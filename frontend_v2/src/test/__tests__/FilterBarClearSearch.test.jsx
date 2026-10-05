import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { FilterBar } from '../../components/dashboard/FilterBar';

/**
 * "Clear search" used to be a button that un-cleared the search.
 *
 * `FilterBar` debounces the search box and writes the debounced value up to the
 * parent from an effect. The clear handler wrote `''` straight to the parent
 * without touching the debounce, so the timer armed by the last keystroke was
 * still pending: 400 ms after the click it fired the OLD term back up. The
 * recorded call sequence on the component before the fix was
 *
 *   [{search: "", sort: "date_desc"}, {search: "sunset", sort: "date_desc"}]
 *
 * — the second call winning, the input repopulating with "sunset", and the
 * gallery filter never cleared while the UI showed a cleared field. A control
 * that reports success and performs the opposite.
 *
 * The fix gives `useDebounce` a `cancel(next)` that drops the pending timer and
 * adopts the caller's value, and the clear handler uses it.
 */
describe('FilterBar clear search', () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    function mount() {
        const onFilterChange = vi.fn();
        let filters = { search: 'sunset', sort: 'date_desc' };
        const view = render(
            <FilterBar
                filters={filters}
                onFilterChange={(next) => {
                    onFilterChange(next);
                    filters = next;
                    view.rerender(
                        <FilterBar filters={filters} onFilterChange={(n) => {
                            onFilterChange(n);
                            filters = n;
                        }} />
                    );
                }}
            />
        );
        return { onFilterChange, view };
    }

    it('does not re-emit the old search term after clearing', () => {
        const { onFilterChange } = mount();

        fireEvent.click(screen.getByLabelText('Clear search'));
        expect(onFilterChange).toHaveBeenCalledTimes(1);
        expect(onFilterChange).toHaveBeenLastCalledWith({ search: '', sort: 'date_desc' });

        // Let every pending debounce timer fire. Before the fix this is where
        // `{search: "sunset"}` came back.
        act(() => {
            vi.advanceTimersByTime(1000);
        });

        expect(onFilterChange).toHaveBeenCalledTimes(1);
        expect(screen.getByLabelText('Search filters')).toHaveValue('');
        expect(screen.queryByLabelText('Clear search')).toBeNull();
    });

    it('still debounces ordinary typing', () => {
        const onFilterChange = vi.fn();
        const { rerender } = render(
            <FilterBar filters={{ search: '', sort: 'date_desc' }} onFilterChange={onFilterChange} />
        );

        fireEvent.change(screen.getByLabelText('Search filters'), {
            target: { value: 'portrait' },
        });

        act(() => {
            vi.advanceTimersByTime(100);
        });
        expect(onFilterChange).not.toHaveBeenCalled();

        act(() => {
            vi.advanceTimersByTime(400);
        });
        expect(onFilterChange).toHaveBeenCalledTimes(1);
        expect(onFilterChange).toHaveBeenLastCalledWith({
            search: 'portrait',
            sort: 'date_desc',
        });
        rerender(
            <FilterBar filters={{ search: 'portrait', sort: 'date_desc' }} onFilterChange={onFilterChange} />
        );
    });
});