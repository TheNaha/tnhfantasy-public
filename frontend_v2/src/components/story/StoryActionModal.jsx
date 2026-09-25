import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, PenLine, Expand, ScrollText, Check, X } from 'lucide-react';

const ACTION_META = {
    rewrite: { label: 'Rewrite Selection', icon: PenLine, hint: 'Rewrites the selected passage. The result replaces your selection when applied.', accent: 'text-indigo-400', button: 'bg-indigo-600 hover:bg-indigo-500' },
    expand: { label: 'Expand Selection', icon: Expand, hint: 'Expands the selected passage with richer detail. The result replaces your selection when applied.', accent: 'text-purple-400', button: 'bg-purple-600 hover:bg-purple-500' },
    summarize: { label: 'Summarize', icon: ScrollText, hint: 'Produces a tight synopsis of the selected text (or whole chapter). The result is inserted at your cursor when applied.', accent: 'text-emerald-400', button: 'bg-emerald-600 hover:bg-emerald-500' },
};

export default function StoryActionModal({
    open,
    action,
    selectionText,
    directive,
    onDirectiveChange,
    isRunning,
    result,
    onConfirm,
    onApply,
    onClose,
}) {
    const meta = ACTION_META[action] || ACTION_META.rewrite;
    const Icon = meta.icon;

    return (
        <AnimatePresence>
            {open && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                    onClick={isRunning ? undefined : onClose}
                >
                    <motion.div
                        role="dialog"
                        aria-modal="true"
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-lg shadow-2xl max-h-[80vh] flex flex-col"
                        onClick={e => e.stopPropagation()}
                    >
                        <h3 className="text-lg font-semibold text-gray-100 flex items-center gap-2 mb-2">
                            <Icon size={18} className={meta.accent} />
                            {meta.label}
                        </h3>
                        {!result && (
                            <>
                                <p className="text-sm text-gray-400 mb-3">{meta.hint}</p>
                                <div className="bg-gray-800/40 border border-gray-700/40 rounded-lg px-3 py-2 mb-3 max-h-28 overflow-y-auto">
                                    <p className="text-xs text-gray-500 mb-1">Selected passage</p>
                                    <p className="text-sm text-gray-300 whitespace-pre-wrap line-clamp-4">{selectionText}</p>
                                </div>
                                <input
                                    type="text"
                                    value={directive}
                                    onChange={e => onDirectiveChange(e.target.value)}
                                    placeholder="Directive for the AI (optional) — e.g. 'make it tenser', 'trim by half'"
                                    className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-2.5 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-indigo-500/50 mb-4"
                                    autoFocus
                                    onKeyDown={e => e.key === 'Enter' && onConfirm()}
                                />
                            </>
                        )}
                        {result && (
                            <div className="flex-1 min-h-0 overflow-y-auto bg-gray-800/40 border border-gray-700/40 rounded-lg px-4 py-3 mb-4">
                                <p className="text-xs text-gray-500 mb-2">AI result — review before applying</p>
                                <p className="text-sm text-gray-200 whitespace-pre-wrap">{result}</p>
                            </div>
                        )}
                        <div className="flex gap-2 justify-end">
                            <button
                                onClick={onClose}
                                disabled={isRunning}
                                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors disabled:opacity-50"
                            >
                                {result ? 'Discard' : 'Cancel'}
                            </button>
                            {result ? (
                                <button
                                    onClick={onApply}
                                    className={`px-4 py-2 text-sm text-white rounded-lg transition-colors flex items-center gap-2 ${meta.button}`}
                                >
                                    <Check size={14} />
                                    Apply
                                </button>
                            ) : (
                                <button
                                    onClick={onConfirm}
                                    disabled={isRunning || !selectionText.trim()}
                                    className={`px-4 py-2 text-sm text-white rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 ${meta.button}`}
                                >
                                    {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Icon size={14} />}
                                    {isRunning ? 'Working...' : 'Generate'}
                                </button>
                            )}
                        </div>
                        {result && (
                            <button
                                onClick={() => onApply(true)}
                                className="mt-2 text-xs text-gray-500 hover:text-gray-300 transition-colors self-end flex items-center gap-1"
                            >
                                <X size={10} /> Insert at cursor instead
                            </button>
                        )}
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
}
