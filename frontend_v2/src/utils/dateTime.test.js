import { describe, expect, it } from 'vitest';
import { getLatestDate, parseGalleryDate } from './dateTime';

describe('dateTime utils', () => {
    it('parses unix timestamps in seconds', () => {
        const parsed = parseGalleryDate(1710000000);
        expect(parsed.getTime()).toBe(1710000000 * 1000);
    });

    it('treats naive datetime strings as UTC', () => {
        const naive = parseGalleryDate('2026-03-07T02:00:00');
        const utc = parseGalleryDate('2026-03-07T02:00:00Z');

        expect(naive.getTime()).toBe(utc.getTime());
    });

    it('keeps explicit timezone offsets', () => {
        const offset = parseGalleryDate('2026-03-07T02:00:00+07:00');
        const zulu = parseGalleryDate('2026-03-06T19:00:00Z');

        expect(offset.getTime()).toBe(zulu.getTime());
    });

    it('returns latest date from mixed formats', () => {
        const latest = getLatestDate([
            1709980000,
            '2024-03-09T12:00:00Z',
            '2024-03-09T13:00:00'
        ]);

        expect(latest.toISOString()).toBe('2024-03-09T13:00:00.000Z');
    });
});
