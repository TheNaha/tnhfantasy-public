/**
 * Option-list helpers for enumerations whose truth lives outside this repo.
 *
 * The sampler and scheduler vocabularies in `generation.js` are copied out of the
 * installed ComfyUI's `KSampler` node. A value that list does not contain is one
 * this ComfyUI never sent — but it can still arrive in the app, from a source
 * that is not this ComfyUI: an image generated on another rig and imported into
 * the gallery, or one generated before this list was complete. `reuseParameters`
 * reads `sampler_name` and `scheduler` off stored image metadata and pre-fills
 * the form with them.
 *
 * A `<select>` whose `value` has no matching `<option>` renders as BLANK. Not an
 * error, not a fallback — the control simply shows nothing, and the next submit
 * sends an empty string. So an unrecognised value silently deleted the user's
 * own parameter, on the one screen whose whole job is reproducing an image.
 *
 * `withCurrentOption` keeps the unknown value visible and submittable by putting
 * it at the top, and marks it so the UI can say it came from the image rather
 * than from the vocabulary.
 */

/**
 * Append `current` to `options` when it is absent, so a `<select>` can render it.
 *
 * @param {string[]} options - The known-vocabulary order, preserved as-is.
 * @param {string|null|undefined} current - The value the control should show.
 * @returns {string[]} `options`, unchanged when `current` is known or empty.
 */
export function withCurrentOption(options, current) {
    if (current === null || current === undefined || current === '') return options;
    return options.includes(current) ? options : [current, ...options];
}

/**
 * True when `current` is outside the known vocabulary, so a caller can label it.
 *
 * An empty `current` is not "unknown" — nothing is selected yet, and saying
 * "unrecognized sampler" next to an untouched form is noise.
 */
export function isOutsideVocabulary(options, current) {
    if (current === null || current === undefined || current === '') return false;
    return !options.includes(current);
}
