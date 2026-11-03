/**
 * A single metric card: a large value with a small label above it.
 *
 * Shared by the model metadata/detail/import modals so the Downloads / Likes /
 * Base Model stat pair is rendered in one place. The wrapper grid (column
 * count, background, border) stays on the consumer since it differs per
 * placement; this component owns only the card's inner markup.
 *
 * @param {string} label   Displayed label text (consumer controls casing).
 * @param {string|number} value   Large value, already formatted by the caller.
 * @param {string} [colorClass='text-white'] Tailwind color for the value.
 * @param {string} [labelClass='text-xs text-gray-500'] Tailwind classes for the label.
 */
export default function StatCard({ label, value, colorClass = 'text-white', labelClass = 'text-xs text-gray-500' }) {
    return (
        <div className="text-center">
            <div className={`text-lg font-bold ${colorClass}`}>{value}</div>
            <div className={labelClass}>{label}</div>
        </div>
    );
}
