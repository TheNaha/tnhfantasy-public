/**
 * Browser file downloads.
 *
 * ONE place that turns a payload into a saved file, because the three copies
 * that did this job each got it wrong in their own way: one revoked the object
 * URL in the same tick as `a.click()` (Firefox drops the download), one
 * appended the anchor to `document.body` and two did not, and the story export
 * path built `new Blob([data?.content || ''])` from a response that was already
 * a `Blob` — so EPUB, comic-PDF and webtoon exports silently saved a 0-byte
 * file and then reported success.
 *
 * The rule the export path was missing: `api.get(..., { responseType: 'blob' })`
 * resolves to a real `Blob`, which has no `.content`, no `.blob()` method and no
 * `.headers`. Anything that is already binary must be handed to `triggerFile`
 * untouched.
 */

const REVOKE_DELAY_MS = 1000;

/**
 * Hand a blob to the browser as a download and release the object URL once the
 * download has certainly started.
 *
 * @param {Blob|string} blob
 * @param {string} filename
 */
export function triggerFile(blob, filename) {
    const payload = blob instanceof Blob ? blob : new Blob([blob]);
    const url = URL.createObjectURL(payload);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    // Not synchronously: revoking in the same tick as click() aborts the
    // download in Firefox and older Safari.
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}

/** Download `data` as pretty-printed JSON. */
export function downloadJson(data, filename) {
    triggerFile(JSON.stringify(data, null, 2), filename);
}

/** Download a text payload (`md`, `csv`, plain text). */
export function downloadText(text, filename, type = 'text/plain') {
    triggerFile(new Blob([text], { type }), filename);
}

/** Open a file picker and resolve with the chosen `File`, or `null`. */
export function pickFile({ accept } = {}) {
    return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        if (accept) input.accept = accept;
        input.onchange = () => resolve(input.files?.[0] ?? null);
        // A cancelled picker fires no event in most browsers; resolve on focus
        // returning to the window so the caller is never left awaiting forever.
        window.addEventListener(
            'focus',
            () => setTimeout(() => resolve(input.files?.[0] ?? null), 300),
            { once: true },
        );
        input.click();
    });
}