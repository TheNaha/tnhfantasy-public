import { describe, it, expect } from 'vitest';
import { buildExcerpt, buildStoryOutline, countWords, formatWordCount } from './storyOutline';

const chapters = [
    {
        id: 'ch-2',
        chapter_number: 2,
        title: 'The Long Road',
        content: 'They walked until the sun bled out over the ridge.',
        beats: [{ id: 'b1' }, { id: 'b2' }],
        image_paths: ['a.png'],
        updated_at: '2024-03-02T00:00:00Z',
    },
    {
        id: 'ch-1',
        chapter_number: 1,
        title: 'Arrival',
        content: 'The gate closed behind them with a sound like thunder.',
        beats: [],
        image_paths: [],
        updated_at: '2024-03-01T00:00:00Z',
    },
];

describe('countWords', () => {
    it('counts whitespace-separated tokens', () => {
        expect(countWords('one two three')).toBe(3);
    });

    it('returns 0 for blank or non-string input', () => {
        expect(countWords('   ')).toBe(0);
        expect(countWords(null)).toBe(0);
    });
});

describe('buildExcerpt', () => {
    it('collapses whitespace', () => {
        expect(buildExcerpt('a\n\n  b')).toBe('a b');
    });

    it('truncates long content with an ellipsis', () => {
        const excerpt = buildExcerpt('word '.repeat(100), 20);
        expect(excerpt.endsWith('…')).toBe(true);
        expect(excerpt.length).toBeLessThanOrEqual(21);
    });
});

describe('buildStoryOutline', () => {
    it('sorts chapters by number and derives titles', () => {
        const outline = buildStoryOutline(chapters);
        expect(outline.chapters.map(c => c.id)).toEqual(['ch-1', 'ch-2']);
        expect(outline.chapters[0].title).toBe('Arrival');
    });

    it('falls back to a positional title and number', () => {
        const outline = buildStoryOutline([{ id: 'x', content: 'hi' }]);
        expect(outline.chapters[0]).toMatchObject({ number: 1, title: 'Chapter 1' });
    });

    it('marks the active chapter and totals words', () => {
        const outline = buildStoryOutline(chapters, { activeChapterId: 'ch-2' });
        expect(outline.chapters[1].isActive).toBe(true);
        expect(outline.chapters[0].isActive).toBe(false);
        expect(outline.totalWords).toBe(20);
    });

    it('computes progress against a word count goal', () => {
        const outline = buildStoryOutline([{ id: 'x', content: 'one two three four' }], { wordCountGoal: 8 });
        expect(outline.progress).toBe(50);
    });

    it('caps progress at 100 and ignores invalid goals', () => {
        expect(buildStoryOutline([{ id: 'x', content: 'a b c d' }], { wordCountGoal: 1 }).progress).toBe(100);
        const noGoal = buildStoryOutline(chapters);
        expect(noGoal.progress).toBeNull();
        expect(noGoal.wordCountGoal).toBeNull();
    });

    it('tolerates missing input', () => {
        expect(buildStoryOutline(undefined).chapters).toEqual([]);
    });
});

describe('formatWordCount', () => {
    it('formats small and large counts', () => {
        expect(formatWordCount(0)).toBe('0 words');
        expect(formatWordCount(512)).toBe('512 words');
        expect(formatWordCount(2500)).toBe('2.5k words');
    });
});
