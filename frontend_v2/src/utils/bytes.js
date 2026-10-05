/**
 * Byte-size formatting.
 *
 * ONE convention, because nine ad-hoc copies did not agree: the same 2 GB
 * checkpoint read as "2048 MB" in the installed-models table, "2.00 GB" in the
 * model detail modal, "2048MB" in the generator's checkpoint dropdown and
 * "2.0 GB" in the model picker — four renderings of one file, on four screens
 * the user moves between while deciding whether a download is worth making.
 *
 * The convention:
 *   - steps of 1024, labelled `B`, `KB`, `MB`, `GB`, `TB`. The backend counts
 *     `size` in bytes and `size_kb` in kibibytes, so binary steps are what the
 *     API already speaks; decimal steps would disagree with it.
 *   - the largest unit that leaves a value of at least 1, so a 2 GB model is
 *     never "0.00 GB" and a 900 kB file is never "0 MB".
 *   - one decimal place, except whole bytes.
 *   - a space before the unit.
 *   - `unknown size` for anything that is not a finite non-negative number.
 *
 * `size_kb` — the field on `/api/files` and `/api/models/external` — is
 * kibibytes, so convert with `formatBytes(size_kb * KB)`. Two call sites
 * divided it by 1024 twice inline to reach "GB", which is correct arithmetic
 * and still two places to keep correct.
 *
 * There is deliberately no `unit` or `decimals` option. A fixed unit is how
 * `size / 1024 / 1024` rendered a 200 MB model as "0.00 GB", and a per-call
 * rounding is how the four readings above happened.
 */
export const KB = 1024;
export const MB = KB * 1024;
export const GB = MB * 1024;
export const TB = GB * 1024;

const STEPS = [
    [TB, 'TB'],
    [GB, 'GB'],
    [MB, 'MB'],
    [KB, 'KB'],
];

export function formatBytes(bytes) {
    const value = typeof bytes === 'string' && bytes.trim() !== '' ? Number(bytes) : bytes;
    if (!Number.isFinite(value) || value < 0) return 'unknown size';
    for (const [step, label] of STEPS) {
        if (value >= step) return `${(value / step).toFixed(1)} ${label}`;
    }
    return `${Math.round(value)} B`;
}

export default formatBytes;