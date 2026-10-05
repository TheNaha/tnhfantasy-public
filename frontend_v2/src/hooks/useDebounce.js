import { useState, useEffect } from 'react';

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
    const [debouncedValue, setDebouncedValue] = useState(value);

    useEffect(() => {
        const handler = setTimeout(() => {
            setDebouncedValue(value);
        }, delay);

        return () => {
            clearTimeout(handler);
        };
    }, [value, delay]);

    return debouncedValue;
}
