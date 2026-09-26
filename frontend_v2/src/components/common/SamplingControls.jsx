import React, { useCallback, useEffect, useRef, useState } from 'react';

const FIELDS = [
    { key: 'temperature', label: 'Temp', min: 0, max: 2, step: 0.05 },
    { key: 'top_p', label: 'Top P', min: 0, max: 1, step: 0.01 },
    { key: 'max_output_tokens', label: 'Max Tokens', min: 16, max: 32768, step: 16, int: true },
    { key: 'frequency_penalty', label: 'Freq Pen', min: -2, max: 2, step: 0.1 },
    { key: 'presence_penalty', label: 'Pres Pen', min: -2, max: 2, step: 0.1 },
];

/**
 * Coalescing window for a commit. A held number spinner, or a blur that races an
 * Enter, used to produce one PATCH (and one prefix invalidation) per event.
 */
const COMMIT_DEBOUNCE_MS = 250;

const fieldText = (value) => (value == null ? '' : String(value));

/** `''` means "inherit the global default"; `undefined` means unparseable. */
function parseFieldText(text, int) {
    if (text.trim() === '') return null;
    const parsed = int ? parseInt(text, 10) : parseFloat(text);
    return Number.isFinite(parsed) ? parsed : undefined;
}

/**
 * One override field. The text in the box is a local draft until the user is
 * done with it, so `onChange` fires once per gesture instead of once per
 * keystroke — the same commit-on-release shape as ContextSlider, which keys off
 * `onMouseUp`/`onKeyUp`.
 */
function SamplingField({ field, serverValue, onCommit }) {
    const { key, label, min, max, step, int } = field;
    const serverText = fieldText(serverValue);

    const [draft, setDraft] = useState(serverText);
    const [syncedText, setSyncedText] = useState(serverText);

    // Re-sync when the committed value changes underneath us — a different chat
    // or story, or the `onError` rollback in useUpdateChat. Adjusted during
    // render rather than in an effect so there is no window in which a queued
    // effect can overwrite a draft the user has started typing.
    if (serverText !== syncedText) {
        setSyncedText(serverText);
        setDraft(serverText);
    }

    const commitRef = useRef(onCommit);
    useEffect(() => { commitRef.current = onCommit; });

    const timerRef = useRef(null);
    const pendingRef = useRef(null);
    const clearTimer = useCallback(() => {
        if (timerRef.current !== null) {
            clearTimeout(timerRef.current);
            timerRef.current = null;
        }
    }, []);

    const discard = useCallback(() => {
        clearTimer();
        pendingRef.current = null;
    }, [clearTimer]);

    const flush = useCallback(() => {
        clearTimer();
        const pending = pendingRef.current;
        pendingRef.current = null;
        if (pending) commitRef.current(pending);
    }, [clearTimer]);

    const commit = useCallback((update) => {
        if (pendingRef.current && pendingRef.current.key !== update.key) {
            // A different field is already queued; send that one first so the
            // two PATCHes cannot land out of order.
            const queued = pendingRef.current;
            pendingRef.current = update;
            commitRef.current(queued);
            return;
        }
        pendingRef.current = update;
        if (timerRef.current !== null) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(flush, COMMIT_DEBOUNCE_MS);
    }, [flush]);

    // The entity changed, so anything still queued belonged to the previous
    // one. Without this the timer would fire a stale draft through `onChange`,
    // which resolves the chat id at call time. Deliberately not an effect
    // *cleanup*: on unmount the pending commit is flushed below instead, and
    // cleanups run in declaration order, so a cleanup here would wipe it first.
    const lastServerTextRef = useRef(serverText);
    useEffect(() => {
        if (lastServerTextRef.current !== serverText) discard();
        lastServerTextRef.current = serverText;
    }, [serverText, discard]);

    // A commit the user has already made must not be lost to an unmount.
    useEffect(() => () => flush(), [flush]);

    const parsed = parseFieldText(draft, int);
    const inherited = serverValue == null;

    const commitDraft = useCallback(() => {
        if (parsed === undefined) return;               // mid-typing, not a number yet
        if (parsed === (serverValue ?? null)) return;    // unchanged
        commit({ [key]: parsed });
    }, [commit, key, parsed, serverValue]);

    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            commitDraft();
        }
    }, [commitDraft]);

    const handleReset = useCallback(() => {
        setDraft('');
        commit({ [key]: null });
    }, [commit, key]);

    return (
        <label className="flex flex-col gap-1">
            <span className="text-[9px] uppercase tracking-wider text-gray-500 font-bold">{label}</span>
            <div className="flex items-center gap-1">
                <input
                    type="number"
                    min={min}
                    max={max}
                    step={step}
                    placeholder="global"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={commitDraft}
                    onKeyDown={handleKeyDown}
                    onMouseUp={commitDraft}
                    onTouchEnd={commitDraft}
                    title="Press Enter or click away to save"
                    className="w-full bg-gray-800 border border-gray-700 text-xs rounded px-2 py-1 text-gray-300 focus:outline-none placeholder-gray-600"
                />
                {!inherited && (
                    <button
                        onClick={handleReset}
                        title="Inherit global default"
                        className="p-0.5 text-gray-500 hover:text-red-400 transition-colors"
                    >
                        ×
                    </button>
                )}
            </div>
        </label>
    );
}

/**
 * Shared per-entity LLM sampling override controls (chat + story panels).
 * Blank field = inherit the global default configured in Settings.
 *
 * Fields commit on blur, on Enter, and on the number-spinner release — never
 * per keystroke. Committing on every keystroke meant typing `0.85` into
 * temperature fired four PATCHes, and every PATCH invalidates a three-element
 * prefix that matches the chat's system-prompt, jobs and images sub-queries.
 */
export default function SamplingControls({ values = {}, onChange }) {
    const anySet = FIELDS.some(f => values[f.key] != null);

    return (
        <div>
            <div className="flex items-center justify-between mb-1.5">
                <p className="text-xs text-gray-300 font-medium">Sampling</p>
                <span className="text-[10px] text-gray-500 font-mono">
                    {anySet ? 'custom overrides' : 'Global defaults'}
                </span>
            </div>
            <div className="grid grid-cols-2 gap-2">
                {FIELDS.map((field) => (
                    <SamplingField
                        key={field.key}
                        field={field}
                        serverValue={values[field.key]}
                        onCommit={onChange}
                    />
                ))}
            </div>
            {anySet && (
                <button
                    onClick={() => onChange(Object.fromEntries(FIELDS.map(f => [f.key, null])))}
                    className="mt-1.5 text-[9px] text-gray-500 hover:text-red-400 transition-colors"
                >
                    Reset all to global defaults
                </button>
            )}
        </div>
    );
}
