import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { useDebounce } from './useDebounce';

describe('useDebounce', () => {
    it('should return initial value immediately', () => {
        const { result } = renderHook(() => useDebounce('initial', 500));
        expect(result.current).toBe('initial');
    });

    it('should debounce value update', () => {
        vi.useFakeTimers();
        const { result, rerender } = renderHook(({ value, delay }) => useDebounce(value, delay), {
            initialProps: { value: 'initial', delay: 500 },
        });

        rerender({ value: 'updated', delay: 500 });

        // Value shouldn't update immediately
        expect(result.current).toBe('initial');

        // Fast-forward time
        act(() => {
            vi.advanceTimersByTime(499);
        });
        expect(result.current).toBe('initial');

        // Fast-forward time to complete delay
        act(() => {
            vi.advanceTimersByTime(1);
        });
        expect(result.current).toBe('updated');

        vi.useRealTimers();
    });

    it('should use default delay if not provided', () => {
        vi.useFakeTimers();
        const { result, rerender } = renderHook(({ value }) => useDebounce(value), {
            initialProps: { value: 'initial' },
        });

        rerender({ value: 'updated' });

        expect(result.current).toBe('initial');

        // Default delay is 300ms
        act(() => {
            vi.advanceTimersByTime(299);
        });
        expect(result.current).toBe('initial');

        act(() => {
            vi.advanceTimersByTime(1);
        });
        expect(result.current).toBe('updated');

        vi.useRealTimers();
    });

    it('should clear previous timer on new update', () => {
        vi.useFakeTimers();
        const { result, rerender } = renderHook(({ value, delay }) => useDebounce(value, delay), {
            initialProps: { value: 'initial', delay: 500 },
        });

        rerender({ value: 'update1', delay: 500 });

        act(() => {
            vi.advanceTimersByTime(250);
        });
        expect(result.current).toBe('initial');

        rerender({ value: 'update2', delay: 500 });

        act(() => {
            vi.advanceTimersByTime(250);
        });
        // Total 500ms passed since first update, but timer was reset
        expect(result.current).toBe('initial');

        act(() => {
            vi.advanceTimersByTime(250);
        });
        // Total 500ms passed since second update
        expect(result.current).toBe('update2');

        vi.useRealTimers();
    });
});
