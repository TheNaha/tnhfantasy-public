const EXCERPT_LENGTH = 140;

export function countWords(text) {
    if (typeof text !== 'string') return 0;
    const trimmed = text.trim();
    if (!trimmed) return 0;
    return trimmed.split(/\s+/).length;
}

/** First paragraph-ish slice of the chapter prose, collapsed to one line. */
export function buildExcerpt(content, length = EXCERPT_LENGTH) {
    if (typeof content !== 'string') return '';
    const flat = content.replace(/\s+/g, ' ').trim();
    if (flat.length <= length) return flat;
    return `${flat.slice(0, length).trimEnd()}…`;
}

/**
 * Derives a flat outline from the chapter list. Pure — no fetching, no schema
 * assumptions beyond the existing `chapters` payload.
 */
export function buildStoryOutline(chapters, { activeChapterId, wordCountGoal } = {}) {
    const list = (Array.isArray(chapters) ? chapters : [])
        .filter(Boolean)
        .map((chapter, index) => ({
            id: chapter.id,
            number: Number.isFinite(chapter.chapter_number) ? chapter.chapter_number : index + 1,
            title: chapter.title?.trim() || `Chapter ${index + 1}`,
            wordCount: countWords(chapter.content),
            excerpt: buildExcerpt(chapter.content),
            beats: Array.isArray(chapter.beats) ? chapter.beats.length : 0,
            images: Array.isArray(chapter.image_paths) ? chapter.image_paths.length : 0,
            updatedAt: chapter.updated_at || null,
            isActive: chapter.id === activeChapterId,
        }))
        .sort((a, b) => a.number - b.number);

    const totalWords = list.reduce((sum, chapter) => sum + chapter.wordCount, 0);
    const goal = Number.isFinite(wordCountGoal) && wordCountGoal > 0 ? wordCountGoal : null;
    const progress = goal ? Math.min(100, Math.round((totalWords / goal) * 100)) : null;

    return { chapters: list, totalWords, wordCountGoal: goal, progress };
}

export function formatWordCount(words) {
    if (!Number.isFinite(words) || words <= 0) return '0 words';
    if (words < 1000) return `${words} words`;
    return `${(words / 1000).toFixed(1)}k words`;
}
