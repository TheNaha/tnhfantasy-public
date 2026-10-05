import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { History, Loader2, RotateCcw, X, Camera } from 'lucide-react';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { QueryErrorState } from '../common/QueryState';
import { parseGalleryDate } from '../../utils/dateTime';

const SOURCE_META = {
    manual: { label: 'Manual save', className: 'bg-sky-500/15 text-sky-300 border-sky-500/30' },
    pre_retry: { label: 'Before retry', className: 'bg-amber-500/15 text-amber-300 border-amber-500/30' },
    pre_beat_edit: { label: 'Before beat edit', className: 'bg-violet-500/15 text-violet-300 border-violet-500/30' },
    pre_beat_delete: { label: 'Before beat delete', className: 'bg-rose-500/15 text-rose-300 border-rose-500/30' },
    pre_restore: { label: 'Before restore', className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30' },
};

const formatTime = (iso) => {
    if (!iso) return '';
    try {
        // `parseGalleryDate`, not `new Date(iso)`: a snapshot timestamp with no
        // offset is UTC, and the bare constructor reads it as local time, so
        // every revision taken before 08:00 UTC was listed under the wrong day
        // for anyone west of Greenwich.
        return parseGalleryDate(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
        return iso;
    }
};

export default function ChapterRevisionsModal({
    isOpen,
    chapterTitle,
    revisions = [],
    isLoading,
    // The revisions query's failure. `revisions` defaults to `[]`, so a failed
    // GET rendered "No snapshots yet — save one with Snapshot now" and offered
    // the Snapshot button, for a chapter whose entire history was merely
    // unreachable.
    isError = false,
    error = null,
    onRetry,
    isRestoring,
    onRestore,
    onSnapshot,
    onClose,
}) {
    // Escape dismisses, matching every other dialog expectation.
    // `isOpen` is the dialog's own visibility (the name <Modal>/<ModalOverlay> use). Passing a literal `true` registered a
    // permanent window keydown listener for a component that is mounted
    // unconditionally, so a hidden dialog could still react to Escape.
    useEscapeKey(onClose, !!isOpen);

    return (
        <AnimatePresence>
            {isOpen && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                    onClick={isRestoring ? undefined : onClose}
                    data-testid="revisions-modal"
                >
                    <motion.div
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-xl shadow-2xl max-h-[80vh] flex flex-col"
                        onClick={e => e.stopPropagation()}
                    >
                        <h3 className="text-lg font-semibold text-gray-100 flex items-center gap-2 mb-1">
                            <History size={18} className="text-sky-400" />
                            Revision history
                        </h3>
                        <p className="text-xs text-gray-500 mb-4">
                            Snapshots of “{chapterTitle}”. Restoring replaces the prose; beats stay unchanged.
                        </p>
                        <div className="flex-1 min-h-0 overflow-y-auto space-y-2 pr-1">
                            {isLoading && (
                                <div className="flex items-center justify-center py-8 text-gray-500">
                                    <Loader2 size={18} className="animate-spin" />
                                </div>
                            )}
                            {!isLoading && isError && (
                                <div className="py-4">
                                    <QueryErrorState
                                        noun="snapshots"
                                        error={error}
                                        onRetry={onRetry}
                                    />
                                </div>
                            )}
                            {!isLoading && !isError && revisions.length === 0 && (
                                <p className="text-sm text-gray-500 text-center py-8">
                                    No snapshots yet — save one with “Snapshot now”, or let retries and beat edits create them automatically.
                                </p>
                            )}
                            {!isLoading && !isError && revisions.map((rev) => {
                                const meta = SOURCE_META[rev.source] || SOURCE_META.manual;
                                return (
                                    <div
                                        key={rev.id}
                                        className="bg-gray-800/40 border border-gray-700/40 rounded-lg px-3 py-2.5"
                                        data-testid="revision-row"
                                    >
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className={`text-xs px-1.5 py-0.5 rounded border ${meta.className}`}>
                                                {meta.label}
                                            </span>
                                            <span className="text-xs text-gray-500">{formatTime(rev.created_at)}</span>
                                            <span className="text-xs text-gray-600 ml-auto mr-2">{rev.word_count} words</span>
                                            <button
                                                title="Restore this revision"
                                                disabled={isRestoring}
                                                onClick={() => onRestore(rev)}
                                                className="text-gray-400 hover:text-sky-300 transition-colors disabled:opacity-50 flex items-center gap-1 text-xs"
                                            >
                                                {isRestoring ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
                                                Restore
                                            </button>
                                        </div>
                                        {rev.preview && (
                                            <p className="text-xs text-gray-400 whitespace-pre-wrap line-clamp-2">{rev.preview}</p>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                        <div className="flex justify-end gap-2 mt-4">
                            {onSnapshot && (
                                <button
                                    onClick={onSnapshot}
                                    disabled={isRestoring}
                                    className="px-3 py-2 text-sm text-sky-300 hover:text-sky-200 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                                    title="Save a snapshot of the chapter's current prose"
                                >
                                    <Camera size={14} /> Snapshot now
                                </button>
                            )}
                            <button
                                onClick={onClose}
                                disabled={isRestoring}
                                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors disabled:opacity-50 flex items-center gap-1"
                            >
                                <X size={14} /> Close
                            </button>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}
