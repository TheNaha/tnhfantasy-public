import { useState } from 'react';
import { AlertTriangle, ArrowRight, CheckCircle2, FileImage, Loader2, Sparkles } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';
import { cardSpecLabel } from '../../api/characterCards';

/**
 * What importing this card would do.
 *
 * The import used to write immediately, so the only way to find out what a
 * card would do was to do it — and re-importing a card created a SECOND
 * character with the same name, silently, because the merge needed an
 * identity the card might not carry.
 *
 * So the flow is now: analyze (writes nothing) -> this -> commit.
 */
export default function CharacterCardImportPreview({
    preview,
    filename,
    onCancel,
    onCommit,
    committing = false,
    error = null,
}) {
    const [scope, setScope] = useState('character');
    const [matchAction, setMatchAction] = useState('auto');

    if (!preview) return null;

    const match = preview.match || {};
    const isUpdate = match.action === 'update';
    const counts = preview.counts || {};

    return (
        <ModalOverlay
            onClose={onCancel}
            className="z-[95] bg-black/80 backdrop-blur-sm"
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="card-import-preview-title"
                data-testid="card-import-preview"
                className="w-full max-w-xl bg-gray-900 rounded-2xl border border-white/10 shadow-2xl overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="px-5 py-4 border-b border-white/5">
                    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
                        Before importing
                    </p>
                    <h2
                        id="card-import-preview-title"
                        className="mt-1 text-lg font-bold text-gray-100"
                    >
                        {preview.name || 'Unnamed character'}
                    </h2>
                    <p className="mt-0.5 text-xs text-gray-500">
                        {filename ? `${filename} · ` : ''}
                        {String(preview.format || '').toUpperCase()}
                        {preview.spec ? ` · ${cardSpecLabel(preview.spec, preview.spec_version)}` : ''}
                    </p>
                </div>

                <div className="px-5 py-4 space-y-3 max-h-[55vh] overflow-y-auto custom-scrollbar">
                    {isUpdate ? (
                        <div
                            className="flex items-start gap-2 rounded-xl border border-sky-500/30 bg-sky-500/5 p-3 text-xs text-sky-200"
                            data-testid="card-import-match"
                        >
                            <ArrowRight size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                            <span>
                                This card identifies <strong>{match.name}</strong>, which is already
                                here. Importing will update it
                                {match.by === 'identity' ? ' (matched by identity)' : ' (matched by name)'}.
                            </span>
                        </div>
                    ) : (
                        <div
                            className="flex items-start gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs text-emerald-200"
                            data-testid="card-import-match"
                        >
                            <CheckCircle2 size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                            <span>This is a new character.</span>
                        </div>
                    )}

                    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                        <p className="text-2xs font-semibold uppercase tracking-wider text-gray-500">
                            What the card holds
                        </p>
                        <dl className="mt-1.5 space-y-1 text-xs">
                            {[
                                ['Description', preview.description],
                                ['Personality', preview.personality],
                                ['Scenario', preview.scenario],
                                ['First message', preview.first_mes],
                                ['Example', preview.mes_example],
                                ['Alternate greetings', counts.alternate_greetings],
                                ['Embedded lorebook entries', counts.lorebook_entries],
                                ['Expression images', counts.expressions],
                            ]
                                .filter(([, value]) => value !== undefined && value !== null && value !== '')
                                .map(([label, value]) => (
                                    <div key={label} className="flex gap-2">
                                        <dt className="w-40 shrink-0 text-gray-500">{label}</dt>
                                        <dd className="min-w-0 flex-1 break-words text-gray-300">
                                            {typeof value === 'number' ? value : String(value)}
                                        </dd>
                                    </div>
                                ))}
                        </dl>
                    </div>

                    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                        <p className="text-2xs font-semibold uppercase tracking-wider text-gray-500">
                            How much to import
                        </p>
                        <div className="mt-2 space-y-1.5">
                            {(preview.scopes || []).map((option) => (
                                <label
                                    key={option.id}
                                    className="flex cursor-pointer items-start gap-2 rounded-lg border border-white/10 p-2 hover:bg-white/5"
                                >
                                    <input
                                        type="radio"
                                        name="card-import-scope"
                                        value={option.id}
                                        checked={scope === option.id}
                                        onChange={() => setScope(option.id)}
                                        className="mt-0.5 accent-cyan-500"
                                    />
                                    <span className="min-w-0">
                                        <span className="block text-xs font-medium text-gray-200">
                                            {option.label}
                                        </span>
                                        <span className="block text-2xs leading-4 text-gray-500">
                                            {option.detail}
                                        </span>
                                    </span>
                                </label>
                            ))}
                        </div>
                    </div>

                    {isUpdate && (
                        <div className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
                            <p className="text-2xs font-semibold uppercase tracking-wider text-gray-500">
                                What to do with the match
                            </p>
                            <div className="mt-2 flex flex-wrap gap-1.5">
                                {[
                                    ['auto', 'Update it'],
                                    ['create', 'Create a new one'],
                                ].map(([value, label]) => (
                                    <button
                                        key={value}
                                        type="button"
                                        onClick={() => setMatchAction(value)}
                                        className={`rounded-lg border px-2.5 py-1 text-2xs transition-colors ${
                                            matchAction === value
                                                ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                                                : 'border-white/10 bg-white/5 text-gray-400 hover:text-gray-200'
                                        }`}
                                    >
                                        {label}
                                    </button>
                                ))}
                            </div>
                        </div>
                    )}

                    {error && (
                        <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/5 p-3 text-xs text-rose-200">
                            <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                            <span>{error}</span>
                        </div>
                    )}
                </div>

                <div className="flex flex-wrap gap-2 px-5 py-4 border-t border-white/5">
                    <button
                        type="button"
                        onClick={() => onCommit({ scope, matchAction })}
                        disabled={committing}
                        className="btn-primary flex items-center gap-2 disabled:opacity-50"
                    >
                        {committing ? (
                            <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                        ) : (
                            <Sparkles size={14} aria-hidden="true" />
                        )}
                        <span>
                            {scope === 'world'
                                ? 'Build the world'
                                : isUpdate && matchAction !== 'create'
                                  ? 'Update the character'
                                  : 'Import the character'}
                        </span>
                    </button>
                    <button type="button" onClick={onCancel} className="btn-secondary">
                        Cancel
                    </button>
                </div>
            </div>
        </ModalOverlay>
    );
}
