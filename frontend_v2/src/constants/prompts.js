/**
 * Prompt categories the UI offers before the server has told us about any.
 *
 * `usePromptCategories` merges the server's list with these, so the filter row
 * is populated on first paint instead of appearing empty while the request is
 * in flight. They are a fallback, not a filter: a category the server does not
 * have shows up as an empty result rather than being hidden.
 *
 * They lived in four files. Three of those were `= ['All', 'Portrait', …]`
 * defaults on a `useQuery` result that the hook guarantees is a non-empty array,
 * so the three copies were unreachable — a list kept in sync by hand, in three
 * places, that no code path could ever read.
 */
export const DEFAULT_PROMPT_CATEGORIES = [
    'All',
    'Portrait',
    'Landscape',
    'Anime',
    'Abstract',
    'Realistic',
    'Custom',
];