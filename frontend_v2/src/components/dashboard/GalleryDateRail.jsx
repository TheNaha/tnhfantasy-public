import { useMemo } from 'react';
import { CalendarDays, X } from 'lucide-react';

import { useAssetDateHistogram } from '../../hooks/useGallery';

/**
 * Date rail for the gallery.
 *
 * Props:
 *   filters   the gallery filter object. Reads `date_from` / `date_to`.
 *   onChange  called with a NEW filter object; `date_from` / `date_to` are the
 *             only keys written. Clearing deletes them rather than sending
 *             empty strings.
 *
 * The histogram is NOT a prop: this component calls `useAssetDateHistogram`
 * itself and owns the query. Pass `filters` and nothing else. The hook is
 * deliberately scoped by the listing filters only (workspace / character /
 * story / search) and not by the facet selection — a rail scoped to the current
 * selection reports how much has been selected, which is not a navigation aid.
 *
 * Every bound it emits is UTC. The histogram is bucketed with
 * `day_rule: "utc"`, so a local-time day boundary would be offset by the
 * viewer's zone and the tail of the selected day would fall outside the range.
 */

const DAY_MS = 86_400_000;

/**
 * Columns in the rail.
 *
 * A library spanning years has one histogram entry per *day that has images*,
 * which is thousands of entries — at 3px a bar plus a 1px gap that is a
 * 4-pixel smear nobody can click. 48 columns is the largest count that still
 * reads in a ~320px sidebar rail (≈6px per column) and does not become a forest
 * of hairlines in a full-width bar, and it is small enough that a 10-year
 * library still averages ~2.5 active days per column.
 */
const MAX_COLUMNS = 48;

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/** `YYYY-MM-DD` → integer days since the epoch, with no timezone in the way. */
function dayNumber(day) {
    const [year, month, date] = day.split('-').map(Number);
    return Math.round(Date.UTC(year, month - 1, date) / DAY_MS);
}

function dayString(number) {
    return new Date(number * DAY_MS).toISOString().slice(0, 10);
}

function dayStartIso(day) {
    return `${day}T00:00:00Z`;
}

function dayEndIso(day) {
    // The bound is an inclusive instant comparison, not a formatted string, so
    // `23:59:59` would drop the last fractional second of the day in Postgres.
    return `${day}T23:59:59.999999Z`;
}

/** Formatted with an explicit UTC zone: the day keys are UTC days. */
function formatDay(day) {
    const [year, month, date] = day.split('-').map(Number);
    return new Date(Date.UTC(year, month - 1, date)).toLocaleDateString(undefined, {
        timeZone: 'UTC',
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
}

function isDayLike(entry) {
    return Boolean(entry?.day) && DAY_PATTERN.test(entry.day) && Number.isFinite(dayNumber(entry.day));
}

/**
 * One column per day, or one per bucket when the span is too wide to draw.
 *
 * Buckets are cut on the CALENDAR span rather than on the array index, so a
 * column's width means the same amount of time whatever the gaps between active
 * days are. Below `MAX_COLUMNS` days no bucketing happens at all: every day the
 * server reported gets its own clickable column, because a day you can see must
 * be a day you can select.
 */
function buildColumns(days) {
    const usable = (Array.isArray(days) ? days : []).filter(isDayLike);
    if (usable.length === 0) return { columns: [], aggregated: false, spanDays: 0 };

    const counts = usable.reduce((acc, entry) => {
        const number = dayNumber(entry.day);
        acc.set(number, (acc.get(number) || 0) + (entry.count || 0));
        return acc;
    }, new Map());
    const numbers = [...counts.keys()].sort((a, b) => a - b);
    const first = numbers[0];
    const spanDays = numbers[numbers.length - 1] - first + 1;

    if (usable.length <= MAX_COLUMNS) {
        return {
            aggregated: false,
            spanDays,
            columns: numbers.map((number) => ({
                key: dayString(number),
                from: dayString(number),
                to: dayString(number),
                count: counts.get(number),
                aggregated: false,
            })),
        };
    }

    const width = spanDays / MAX_COLUMNS;
    const buckets = new Array(MAX_COLUMNS).fill(0);
    for (const [number, count] of counts) {
        const index = Math.min(MAX_COLUMNS - 1, Math.floor(((number - first) / spanDays) * MAX_COLUMNS));
        buckets[index] += count;
    }
    const columns = buckets.map((count, index) => {
        const start = first + Math.floor(index * width);
        const end = first + Math.min(spanDays, Math.ceil((index + 1) * width)) - 1;
        return {
            key: `${dayString(start)}_${dayString(end)}`,
            from: dayString(start),
            to: dayString(end),
            count,
            aggregated: true,
        };
    });
    return { columns, aggregated: true, spanDays };
}

function columnLabel(column) {
    const range = column.from === column.to ? column.from : `${column.from} to ${column.to}`;
    const images = `${column.count} image${column.count === 1 ? '' : 's'}`;
    return column.aggregated ? `${range} (aggregated), ${images}` : `${range}, ${images}`;
}

/** `filters.date_from` is an instant; its leading date is the UTC day in effect. */
function dayOfInstant(instant) {
    return typeof instant === 'string' && instant.length >= 10 ? instant.slice(0, 10) : null;
}

export function GalleryDateRail({ filters = {}, onChange }) {
    const { data, isLoading } = useAssetDateHistogram(filters);
    const days = useMemo(() => data?.days || [], [data]);

    const { columns, aggregated, spanDays } = useMemo(() => buildColumns(days), [days]);

    const emit = (next) => {
        if (typeof onChange === 'function') onChange(next);
    };

    const clearRange = () => {
        const next = { ...filters };
        delete next.date_from;
        delete next.date_to;
        emit(next);
    };

    const selectedFrom = dayOfInstant(filters.date_from);
    const selectedTo = dayOfInstant(filters.date_to);
    const hasRange = Boolean(selectedFrom && selectedTo);

    const handleSelect = (column) => {
        if (hasRange && column.from === selectedFrom && column.to === selectedTo) {
            clearRange();
            return;
        }
        emit({
            ...filters,
            date_from: dayStartIso(column.from),
            date_to: dayEndIso(column.to),
        });
    };

    const maxCount = columns.reduce((max, column) => Math.max(max, column.count), 0);

    return (
        <div data-testid="gallery-date-rail" className="rounded-xl border border-hairline bg-raised p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-secondary">
                    <CalendarDays size={12} />
                    By date
                </div>
                {hasRange ? (
                    <div className="flex items-center gap-1">
                        <span data-testid="date-rail-range" className="text-2xs text-primary">
                            {formatDay(selectedFrom)} – {formatDay(selectedTo)}
                        </span>
                        <button
                            type="button"
                            data-testid="date-rail-clear"
                            onClick={clearRange}
                            className="flex items-center gap-1 rounded-md border border-hairline px-1.5 py-0.5 text-2xs text-secondary hover:bg-overlay hover:text-primary"
                        >
                            <X size={12} /> Clear
                        </button>
                    </div>
                ) : (
                    <span data-testid="date-rail-range" className="text-2xs text-tertiary">Whole library</span>
                )}
            </div>

            {isLoading && (
                <p data-testid="date-rail-loading" className="py-4 text-center text-2xs text-tertiary">
                    Loading dates…
                </p>
            )}

            {!isLoading && columns.length === 0 && (
                <p data-testid="date-rail-empty" className="py-4 text-center text-2xs text-tertiary">
                    No images in this view yet.
                </p>
            )}

            {columns.length > 0 && (
                <>
                    <div data-testid="date-rail-bars" className="flex h-16 items-end gap-px">
                        {columns.map((column) => {
                            const isSelected = hasRange && column.from === selectedFrom && column.to === selectedTo;
                            // A non-zero day keeps a 3% floor so a single image is
                            // still a click target rather than a hairline.
                            const height = maxCount > 0 && column.count > 0
                                ? Math.max(3, Math.round((column.count / maxCount) * 100))
                                : 0;
                            return (
                                <button
                                    key={column.key}
                                    type="button"
                                    aria-pressed={isSelected}
                                    aria-label={columnLabel(column)}
                                    title={columnLabel(column)}
                                    data-testid={column.aggregated ? 'date-rail-aggregate' : 'date-rail-day'}
                                    data-day={column.from}
                                    data-to={column.to}
                                    onClick={() => handleSelect(column)}
                                    className={[
                                        'flex h-full min-w-0 flex-1 cursor-pointer items-end justify-center p-0',
                                        isSelected ? 'bg-accent-muted' : 'hover:bg-hover',
                                    ].join(' ')}
                                >
                                    {height > 0 ? (
                                        <span
                                            className={isSelected ? 'w-full bg-accent' : 'w-full bg-accent/60'}
                                            style={{ height: `${height}%` }}
                                        />
                                    ) : (
                                        <span className="w-full bg-hairline" style={{ height: '1px' }} />
                                    )}
                                </button>
                            );
                        })}
                    </div>
                    <p data-testid="date-rail-caption" className="mt-1 text-2xs text-tertiary">
                        {aggregated
                            ? `${MAX_COLUMNS} aggregated columns over ${spanDays.toLocaleString()} days — each column is the total of the days it covers.`
                            : `${columns.length} day${columns.length === 1 ? '' : 's'}.`}
                    </p>
                </>
            )}
        </div>
    );
}

export default GalleryDateRail;
