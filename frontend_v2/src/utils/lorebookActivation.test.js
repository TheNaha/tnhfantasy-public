import { describe, it, expect } from 'vitest';
import {
    clipContextText,
    evaluateEntry,
    isAlwaysOnEntry,
    matchEntryKeys,
    selectActivatedEntries,
    summarizeActivation,
} from './lorebookActivation';

const entries = [
    { id: 'e-always', keys: [], content: 'The moon is a liar.' },
    { id: 'e-moon', keys: ['moon', 'lunar'], content: 'The moon rises at dusk.' },
    { id: 'e-dragon', keys: ['dragon'], content: 'Dragons nest in the east.' },
];

describe('clipContextText', () => {
    it('returns an empty string for non-strings', () => {
        expect(clipContextText(null)).toBe('');
        expect(clipContextText(undefined)).toBe('');
        expect(clipContextText(42)).toBe('');
    });

    it('trims whitespace and keeps short text intact', () => {
        expect(clipContextText('  hello moon  ')).toBe('hello moon');
    });

    it('keeps only the tail of long text', () => {
        const long = `${'x'.repeat(50)}dragon`;
        const clipped = clipContextText(long, 20);
        expect(clipped.length).toBeLessThanOrEqual(20);
        expect(clipped.endsWith('dragon')).toBe(true);
    });
});

describe('isAlwaysOnEntry', () => {
    it('treats keyless entries as always-on', () => {
        expect(isAlwaysOnEntry({ keys: [] })).toBe(true);
        expect(isAlwaysOnEntry({})).toBe(true);
        expect(isAlwaysOnEntry({ keys: ['  '] })).toBe(true);
    });

    it('treats keyed entries as conditional', () => {
        expect(isAlwaysOnEntry({ keys: ['moon'] })).toBe(false);
    });

    it('handles missing entries', () => {
        expect(isAlwaysOnEntry(null)).toBe(false);
    });
});

describe('matchEntryKeys', () => {
    it('matches case-insensitively and returns every hit', () => {
        expect(matchEntryKeys({ keys: ['Moon', 'lunar'] }, 'The MOON rises LUNAR tonight')).toEqual(['Moon', 'lunar']);
    });

    it('ignores blank keys and non-string keys', () => {
        expect(matchEntryKeys({ keys: ['', '   ', 5, 'moon'] }, 'moonlit')).toEqual(['moon']);
    });

    it('returns an empty array without text', () => {
        expect(matchEntryKeys({ keys: ['moon'] }, '')).toEqual([]);
        expect(matchEntryKeys(null, 'moon')).toEqual([]);
    });
});

describe('evaluateEntry', () => {
    it('marks keyless entries active without matched keys', () => {
        expect(evaluateEntry({ keys: [] }, 'anything')).toEqual({ active: true, alwaysOn: true, matchedKeys: [] });
    });

    it('marks keyed entries inactive when no key is present', () => {
        const result = evaluateEntry({ keys: ['dragon'] }, 'the tavern was crowded');
        expect(result).toEqual({ active: false, alwaysOn: false, matchedKeys: [] });
    });
});

describe('selectActivatedEntries', () => {
    it('splits entries into injected and dormant', () => {
        const { activated, idle, total } = selectActivatedEntries(entries, 'a moonlit tavern');
        expect(total).toBe(3);
        expect(activated.map(e => e.id)).toEqual(['e-always', 'e-moon']);
        expect(idle.map(e => e.id)).toEqual(['e-dragon']);
    });

    it('annotates activated entries with their matched keys', () => {
        const { activated } = selectActivatedEntries(entries, 'lunar tides');
        const lunar = activated.find(e => e.id === 'e-moon');
        expect(lunar._matchedKeys).toEqual(['lunar']);
        expect(lunar._alwaysOn).toBe(false);
    });

    it('honours the scan limit', () => {
        const many = Array.from({ length: 10 }, (_, i) => ({ id: `e-${i}`, keys: [], content: `c${i}` }));
        const { activated } = selectActivatedEntries(many, 'text', { limit: 4 });
        expect(activated).toHaveLength(4);
    });

    it('tolerates non-array input', () => {
        expect(selectActivatedEntries(undefined, 'x')).toEqual({ activated: [], idle: [], total: 0 });
    });
});

describe('summarizeActivation', () => {
    it('reports active and total counts', () => {
        expect(summarizeActivation(entries, 'the dragon wakes')).toEqual({ active: 2, total: 3 });
    });
});
