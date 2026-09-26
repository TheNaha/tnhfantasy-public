import { AlertTriangle, CheckCircle2, FileWarning, Info, X } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';

function formatBadge(format, spec, specVersion) {
    const parts = [];
    if (format) parts.push(format.toUpperCase());
    if (spec) parts.push(spec);
    if (specVersion) parts.push(`v${specVersion}`);
    return parts.join(' · ') || 'Card';
}

function DetailList({ title, icon: Icon, entries, tone, testId }) {
    if (!entries.length) return null;
    const toneClass = {
        amber: 'border-amber-500/30 bg-amber-500/5 text-amber-200',
        emerald: 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200',
    }[tone] || 'border-white/10 bg-white/5 text-gray-200';

    return (
        <section className={`rounded-xl border p-3 ${toneClass}`} data-testid={testId}>
            <h4 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider">
                <Icon size={13} aria-hidden="true" />
                {title}
            </h4>
            <ul className="mt-2 space-y-1 text-xs">
                {entries.map((entry) => (
                    <li key={entry.id}>
                        <span className="font-medium">{entry.label}</span>
                        {entry.detail && <span className="opacity-75"> — {entry.detail}</span>}
                    </li>
                ))}
            </ul>
        </section>
    );
}

/**
 * Post-import report.
 *
 * Shows what the backend managed to read from the card: detected spec,
 * compatibility warnings, fields that could not be carried over, and
 * extension metadata that was preserved in the character's card metadata.
 */
export default function CharacterCardImportReport({
    character,
    compatibility,
    filename,
    onClose,
    onEdit,
    onChat,
}) {
    if (!character && !compatibility?.hasReport) return null;

    const name = character?.name || 'Character';
    const lost = compatibility?.lost || [];
    const preserved = compatibility?.preserved || [];
    const warnings = compatibility?.warnings || [];
    const lossy = lost.length > 0 || warnings.length > 0;

    return (
        <ModalOverlay
            onClose={onClose}
            className="z-[95] bg-black/80 backdrop-blur-sm"
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="card-import-report-title"
                data-testid="card-import-report"
                className="w-full max-w-xl bg-gray-900 rounded-2xl border border-white/10 shadow-2xl overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-white/5">
                    <div className="min-w-0">
                        <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-cyan-300">
                            Card imported
                        </p>
                        <h2 id="card-import-report-title" className="mt-1 text-lg font-bold text-gray-100">
                            {name}
                        </h2>
                        <p className="mt-0.5 truncate text-xs text-gray-500">
                            {filename ? `${filename} · ` : ''}
                            {formatBadge(compatibility?.format, compatibility?.spec, compatibility?.specVersion)}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        aria-label="Close import report"
                        className="p-2 text-gray-500 hover:text-white rounded-lg hover:bg-white/5 transition-colors"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div className="px-5 py-4 space-y-3 max-h-[55vh] overflow-y-auto custom-scrollbar">
                    {compatibility?.hasReport ? (
                        <div
                            className={`flex items-start gap-2 rounded-xl border p-3 text-xs ${
                                lossy
                                    ? 'border-amber-500/30 bg-amber-500/5 text-amber-200'
                                    : 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200'
                            }`}
                            data-testid="card-import-status"
                        >
                            {lossy ? (
                                <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                            ) : (
                                <CheckCircle2 size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                            )}
                            <span>
                                {lossy
                                    ? 'Imported with warnings. Some card data could not be carried over.'
                                    : 'Fully compatible. All reported card data was imported.'}
                            </span>
                        </div>
                    ) : (
                        <div
                            className="flex items-start gap-2 rounded-xl border border-white/10 bg-white/5 p-3 text-xs text-gray-400"
                            data-testid="card-import-status"
                        >
                            <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
                            <span>
                                The backend did not report compatibility details for this card. Imported fields are
                                shown in the character editor.
                            </span>
                        </div>
                    )}

                    <DetailList
                        title="Warnings"
                        icon={FileWarning}
                        entries={warnings}
                        tone="amber"
                        testId="card-import-warnings"
                    />
                    <DetailList
                        title="Not imported"
                        icon={AlertTriangle}
                        entries={lost}
                        tone="amber"
                        testId="card-import-lost"
                    />
                    <DetailList
                        title="Preserved card metadata"
                        icon={CheckCircle2}
                        entries={preserved}
                        tone="emerald"
                        testId="card-import-preserved"
                    />

                    {compatibility?.lorebookConverted && (
                        <p className="text-xs text-gray-400" data-testid="card-import-lorebook">
                            Embedded character book was converted into a lorebook entity.
                        </p>
                    )}
                    {compatibility?.unknownExtensionsPreserved === false && (
                        <p className="text-xs text-amber-300" data-testid="card-import-extensions-lost">
                            Unrecognized extension data could not be preserved.
                        </p>
                    )}
                </div>

                <div className="flex flex-wrap gap-2 px-5 py-4 border-t border-white/5">
                    {onEdit && (
                        <button
                            type="button"
                            onClick={() => onEdit(character)}
                            className="btn-primary flex items-center gap-2"
                        >
                            Review character
                        </button>
                    )}
                    {onChat && (
                        <button
                            type="button"
                            onClick={() => onChat(character)}
                            className="btn-secondary flex items-center gap-2"
                        >
                            Start chat
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={onClose}
                        className={`btn-secondary ${onEdit || onChat ? 'ml-auto' : ''}`}
                    >
                        Close
                    </button>
                </div>
            </div>
        </ModalOverlay>
    );
}
