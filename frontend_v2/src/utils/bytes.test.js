import { describe, it, expect } from 'vitest';
import { formatBytes, KB, MB, GB, TB } from './bytes';

describe('formatBytes', () => {
    it('formats byte counts', () => {
        expect(formatBytes(512)).toBe('512 B');
        expect(formatBytes(2048)).toBe('2.0 KB');
        expect(formatBytes(5 * MB)).toBe('5.0 MB');
    });

    it('escalates to the largest unit that leaves at least one', () => {
        // The four historical copies disagreed here, and the disagreement was
        // visible: a 2 GB checkpoint rendered as "2048 MB", "2.00 GB",
        // "2048MB" and "2.0 GB" on four screens of the same page.
        const twoGigabytes = 2 * GB;
        expect(formatBytes(twoGigabytes)).toBe('2.0 GB');
        expect(formatBytes(200 * MB)).toBe('200.0 MB');
        expect(formatBytes(900 * KB)).toBe('900.0 KB');
        expect(formatBytes(3 * TB)).toBe('3.0 TB');
    });

    it('converts the backend size_kb field with one multiply', () => {
        // `size_kb` is kibibytes, and two call sites used to divide it by 1024
        // twice inline to reach "GB".
        expect(formatBytes(2 * 1024 * 1024 * KB)).toBe('2.0 GB');
    });

    it('reports a missing or impossible size instead of NaN', () => {
        expect(formatBytes(undefined)).toBe('unknown size');
        expect(formatBytes(null)).toBe('unknown size');
        expect(formatBytes(NaN)).toBe('unknown size');
        expect(formatBytes(-1)).toBe('unknown size');
        expect(formatBytes('')).toBe('unknown size');
    });

    it('accepts the numeric strings the API sometimes returns', () => {
        expect(formatBytes('2048')).toBe('2.0 KB');
        expect(formatBytes('0')).toBe('0 B');
    });

    it('keeps the units the backend speaks', () => {
        expect(KB).toBe(1024);
        expect(MB).toBe(1024 * 1024);
        expect(GB).toBe(1024 * 1024 * 1024);
        expect(TB).toBe(1024 * 1024 * 1024 * 1024);
    });
});