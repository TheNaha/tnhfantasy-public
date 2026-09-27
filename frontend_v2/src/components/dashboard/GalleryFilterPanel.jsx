import { useCallback, useId, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Search, X } from 'lucide-react';

import { FACET_DIMENSIONS, useTagVocabulary } from '../../hooks/useGallery';

/**
 * Faceted filter panel for the gallery.
 *
 * Props (all optional):
 *   facets       `{ lora|tag|checkpoint: [{ value, count, label? }] }` from
 *                `useGallery`'s `data.pages[0].facets`. `label` is only ever
 *                non-null for `lora` (the installed model's display name) and is
 *                display-only: the filter value is always `value`.
 *   filters      the gallery filter object. Reads and writes `lora` / `tag` /
 *                `checkpoint` (comma-separated strings, OR-ed within a
 *                dimension) and counts `date_from` / `date_to` as selections.
 *                Every other key is passed through untouched.
 *   onChange     called with a NEW filter object on every change. Nothing here
 *                mutates `filters`.
 *   totalMatched number of images the current filter matches, or undefined
 *                when the caller has no total (the keyset listing can opt out
 *                of it). Rendered honestly rather than as a fake 0.
 *   onClear      optional. Called instead of emitting a narrowed clear when
 *                the host owns a wider reset (search box, workspace, sort).
 *                When absent, "Clear" removes only the keys this panel owns.
 *
 * The panel never asks for more than `FACET_DIMENSIONS` — the backend caps
 * `group_by` at three and a fourth is a 400, not a silently ignored parameter.
 * The request is made by `useGallery`; this component only renders what came
 * back.
 */

/** The keys this panel owns, and therefore the only ones "Clear" touches. */
const OWNED_KEYS = [...FACET_DIMENSIONS, 'date_from', 'date_to'];

const DIMENSION_LABELS = {
    lora: 'LoRA',
    tag: 'Tags',
    checkpoint: 'Checkpoint',
};

/** Chips shown before "show all". Roughly three wrapped rows in a 320px rail. */
const COLLAPSED_CHIP_LIMIT = 12;

const NO_FILTERS = {};

/**
 * The comma-separated string, defensively.
 *
 * `''`, `undefined` and a stray `,,` all mean "nothing selected", and a value
 * that contains a comma cannot round-trip through this encoding at all — so it
 * is dropped here rather than silently widening the filter to two values.
 */
function parseSelection(raw) {
    if (typeof raw !== 'string') return [];
    const values = [];
    for (const part of raw.split(',')) {
        const value = part.trim();
        if (value && !value.includes(',') && !values.includes(value)) values.push(value);
    }
    return values;
}

function toggleSelection(selected, value) {
    return selected.includes(value)
        ? selected.filter((existing) => existing !== value)
        : [...selected, value];
}

/**
 * Selected values that the counts do not contain come FIRST.
 *
 * A value can drop out of `facets` legitimately: the count for a dimension is
 * computed with that dimension's own filter removed, so selecting a rare LoRA
 * leaves it at the top — but a value whose images were all deleted, or one that
 * the server's `facet_limit` cut off, disappears. Hiding it would leave the user
 * unable to unselect what they just selected.
 */
function buildEntries(counts, selected) {
    const rows = Array.isArray(counts) ? counts : [];
    const returned = new Set(rows.map((row) => String(row?.value)));
    const absent = selected
        .filter((value) => !returned.has(value))
        .map((value) => ({ value, count: null, label: null }));
    return [...absent, ...rows];
}

function FacetChips({ dimension, entries, selected, onToggle }) {
    const [showAll, setShowAll] = useState(false);

    const head = entries.slice(0, COLLAPSED_CHIP_LIMIT);
    // A selected value never hides behind the collapse, even when the server
    // ranked it below the cut.
    const stillSelected = entries
        .slice(COLLAPSED_CHIP_LIMIT)
        .filter((entry) => selected.includes(entry.value));
    const shown = showAll ? entries : [...head, ...stillSelected];
    const hasOverflow = entries.length > COLLAPSED_CHIP_LIMIT;

    if (entries.length === 0) {
        return (
            <p data-testid={`facet-empty-${dimension}`} className="text-2xs text-tertiary">
                No {DIMENSION_LABELS[dimension]?.toLowerCase() ?? dimension} in this view.
            </p>
        );
    }

    return (
        <div className="flex flex-wrap gap-1">
            {shown.map((entry) => {
                const value = String(entry.value);
                const isSelected = selected.includes(value);
                const label = entry.label ?? value;
                const hasCount = typeof entry.count === 'number';
                return (
                    <button
                        key={value}
                        type="button"
                        aria-pressed={isSelected}
                        data-testid={`facet-chip-${dimension}`}
                        data-value={value}
                        onClick={() => onToggle(value)}
                        title={hasCount ? `${label} — ${entry.count}` : `${label} — not in the returned counts`}
                        className={[
                            'flex max-w-full items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs transition-colors',
                            isSelected
                                ? 'border-accent bg-accent-muted text-primary'
                                : 'border-hairline bg-sunken text-secondary hover:bg-overlay hover:text-primary',
                        ].join(' ')}
                    >
                        <span className="truncate">{label}</span>
                        <span className="text-tertiary">{hasCount ? entry.count : '—'}</span>
                    </button>
                );
            })}
            {hasOverflow && (
                <button
                    type="button"
                    data-testid={`facet-${dimension}-more`}
                    onClick={() => setShowAll((value) => !value)}
                    className="rounded-md px-1 py-0.5 text-2xs text-accent hover:text-accent-hover"
                >
                    {showAll ? 'Show less' : `Show all ${entries.length}`}
                </button>
            )}
        </div>
    );
}

/**
 * The tag typeahead.
 *
 * Separate component so the vocabulary query only exists while the tag section
 * is open — it is one shared, 5-minute-stale query, but a collapsed section
 * that still costs a request is a collapsed section nobody trusts.
 */
function TagTypeahead({ selected, onToggle }) {
    const [prefix, setPrefix] = useState('');
    const { data: suggestions, isLoading } = useTagVocabulary(prefix);
    const inputId = useId();
    const trimmed = prefix.trim();
    const list = (suggestions || []).slice(0, 10);

    const commit = (value) => {
        onToggle(value);
        setPrefix('');
    };

    return (
        <div className="mb-2">
            <label htmlFor={inputId} className="sr-only">Find a tag</label>
            <div className="relative">
                <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-tertiary" />
                <input
                    id={inputId}
                    type="text"
                    data-testid="facet-tag-input"
                    value={prefix}
                    onChange={(event) => setPrefix(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' && trimmed) {
                            event.preventDefault();
                            commit(trimmed);
                        }
                    }}
                    placeholder="Find a tag…"
                    className="w-full rounded-md border border-hairline bg-sunken py-1 pl-7 pr-2 text-2xs text-primary placeholder:text-tertiary focus:border-accent focus:outline-none"
                />
            </div>
            {isLoading && <p className="mt-1 text-2xs text-tertiary">Loading tags…</p>}
            {!isLoading && trimmed && list.length === 0 && (
                <p className="mt-1 text-2xs text-tertiary">No tag matches “{trimmed}”.</p>
            )}
            {list.length > 0 && (
                <ul className="mt-1 flex flex-wrap gap-1">
                    {list.map(({ tag, count }) => (
                        <li key={tag}>
                            <button
                                type="button"
                                aria-pressed={selected.includes(tag)}
                                data-testid="facet-tag-suggestion"
                                onClick={() => commit(tag)}
                                className={[
                                    'flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs',
                                    selected.includes(tag)
                                        ? 'border-accent bg-accent-muted text-primary'
                                        : 'border-hairline bg-sunken text-secondary hover:bg-overlay hover:text-primary',
                                ].join(' ')}
                            >
                                <span className="truncate">{tag}</span>
                                <span className="text-tertiary">{count}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

function FacetSection({ dimension, entries, selected, onToggle }) {
    const [open, setOpen] = useState(true);
    const bodyId = useId();
    const label = DIMENSION_LABELS[dimension] ?? dimension;

    return (
        <section className="border-t border-hairline py-2 first:border-t-0">
            <button
                type="button"
                aria-expanded={open}
                aria-controls={bodyId}
                data-testid={`facet-section-${dimension}`}
                onClick={() => setOpen((value) => !value)}
                className="flex w-full items-center justify-between gap-2 text-left"
            >
                <span className="flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-secondary">
                    {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    {label}
                    {selected.length > 0 && (
                        <span data-testid={`facet-selected-${dimension}`} className="text-accent">
                            {selected.length} selected
                        </span>
                    )}
                </span>
                <span className="text-2xs text-tertiary">{entries.length} values</span>
            </button>
            {open && (
                <div id={bodyId} className="mt-2">
                    {dimension === 'tag' && <TagTypeahead selected={selected} onToggle={onToggle} />}
                    <FacetChips
                        dimension={dimension}
                        entries={entries}
                        selected={selected}
                        onToggle={onToggle}
                    />
                </div>
            )}
        </section>
    );
}

export function GalleryFilterPanel({
    facets,
    filters = {},
    onChange,
    totalMatched,
    onClear,
}) {
    // A shared empty object rather than a fresh `{}` per render: this is a
    // dependency of three callbacks, and a new identity each render invalidates
    // all of them.
    const activeFilters = filters || NO_FILTERS;

    const emit = useCallback((next) => {
        if (typeof onChange === 'function') onChange(next);
    }, [onChange]);

    const selections = useMemo(
        () => Object.fromEntries(FACET_DIMENSIONS.map((dim) => [dim, parseSelection(activeFilters[dim])])),
        [activeFilters],
    );

    const selectionCount =
        FACET_DIMENSIONS.reduce((total, dim) => total + selections[dim].length, 0) +
        (activeFilters.date_from ? 1 : 0) +
        (activeFilters.date_to ? 1 : 0);

    const handleToggle = useCallback((dimension, value) => {
        const next = toggleSelection(parseSelection(activeFilters[dimension]), value);
        const updated = { ...activeFilters };
        // An empty string is dropped by the request builder, but leaving the key
        // in place would still make it part of the query key.
        if (next.length) updated[dimension] = next.join(',');
        else delete updated[dimension];
        emit(updated);
    }, [activeFilters, emit]);

    const handleClear = useCallback(() => {
        if (typeof onClear === 'function') {
            onClear();
            return;
        }
        const next = { ...activeFilters };
        OWNED_KEYS.forEach((key) => { delete next[key]; });
        emit(next);
    }, [activeFilters, emit, onClear]);

    return (
        <div data-testid="gallery-filter-panel" className="rounded-xl border border-hairline bg-raised p-3">
            <header className="mb-1 flex items-start justify-between gap-2">
                <div>
                    <h2 className="text-sm font-medium text-primary">Filters</h2>
                    <p data-testid="facet-total" className="text-2xs text-secondary">
                        {typeof totalMatched === 'number'
                            ? `${totalMatched.toLocaleString()} matching image${totalMatched === 1 ? '' : 's'}`
                            : 'Matching total unavailable'}
                    </p>
                </div>
                {selectionCount > 0 && (
                    <button
                        type="button"
                        data-testid="facet-clear"
                        onClick={handleClear}
                        className="flex items-center gap-1 rounded-md border border-hairline px-1.5 py-0.5 text-2xs text-secondary hover:bg-overlay hover:text-primary"
                    >
                        <X size={12} /> Clear ({selectionCount})
                    </button>
                )}
            </header>

            {FACET_DIMENSIONS.map((dimension) => (
                <FacetSection
                    key={dimension}
                    dimension={dimension}
                    entries={buildEntries(facets?.[dimension], selections[dimension])}
                    selected={selections[dimension]}
                    onToggle={(value) => handleToggle(dimension, value)}
                />
            ))}
        </div>
    );
}

export default GalleryFilterPanel;
