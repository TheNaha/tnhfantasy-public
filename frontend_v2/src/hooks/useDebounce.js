import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Debounce a value, with a way to cancel the pending write.
 *
 * Returns `[debouncedValue, cancel]`. `cancel(nextValue)` drops the pending
 * timer and adopts `nextValue` (or the latest input, when called with no
 * argument) as the debounced value immediately.
 *
 * The cancel exists because a plain debounce can *resurrect* a value the caller
 * has already superseded. `FilterBar` debounces the gallery search box and its
 * "Clear search" button writes an empty search straight to the parent, bypassing
 * the debounce — so for 400 ms after the click the timer still held the old term
 * and fired it back at the parent. The field visibly repopulated with the term it
 * had just been told to delete, and the filter was never actually cleared. That
 * is the whole class of "the control reports success and does the opposite".
 *
 * @param {*} value - The value to debounce
 * @param {number} delay - Delay in milliseconds
 * @returns {[*, (nextValue?: *) => void]}
 */
export function useDebouncedValue(value, delay = 300) {
    const [debouncedValue, setDebouncedValue] = useState(value);
    const timer = useRef(null);
    const latest = useRef(value);

    useEffect(() => {
        latest.current = value;
    }, [value]);

    const cancel = useCallback((nextValue) => {
        if (timer.current) {
            clearTimeout(timer.current);
            timer.current = null;
        }
        setDebouncedValue(nextValue === undefined ? latest.current : nextValue);
    }, []);

    useEffect(() => {
        timer.current = setTimeout(() => {
            timer.current = null;
            setDebouncedValue(value);
        }, delay);

        return () => {
            if (timer.current) {
                clearTimeout(timer.current);
                timer.current = null;
            }
        };
    }, [value, delay]);

    return [debouncedValue, cancel];
}

/**
 * Custom hook for debouncing values
 *
 * One definition. This used to be spelled twice — a named export and a default
 * export of the same function — with `DiscoverTab.jsx` on the default and the
 * other five callers on the named. Two spellings of one function means an
 * import line is the only thing distinguishing them, and a rename or a `vi.mock`
 * that names one misses the other.
 *
 * @param {*} value - The value to debounce
 * @param {number} delay - Delay in milliseconds
 * @returns {*} - The debounced value
 */
export function useDebounce(value, delay = 300) {
    return useDebouncedValue(value, delay)[0];
}