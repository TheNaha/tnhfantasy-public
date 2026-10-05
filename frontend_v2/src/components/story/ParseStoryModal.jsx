import React, { useState, useEffect } from 'react';
import { X, Sparkles, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useEscapeKey } from '../../hooks/useEscapeKey';

export default function ParseStoryModal({ isOpen, onClose, onComplete }) {
    useEscapeKey(onClose, !!isOpen);

    const [text, setText] = useState('');
    const [isParsing, setIsParsing] = useState(false);

    // Reset when opened
    useEffect(() => {
        if (!isOpen) {
            // eslint-disable-next-line react-hooks/set-state-in-effect
            setText('');
            setIsParsing(false);
        }
    }, [isOpen]);

    return (
        <AnimatePresence>
            {isOpen && (
                <>
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        onClick={onClose}
                        className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
                    />
                    <motion.div
                        initial={{ opacity: 0, scale: 0.95 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl bg-gray-900 border border-gray-700/60 rounded-2xl shadow-2xl z-50 overflow-hidden flex flex-col max-h-[85vh]"
                    >
                        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800 shrink-0">
                            <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                                <Sparkles className="text-indigo-400" />
                                Import & Parse Story
                            </h2>
                            <button onClick={onClose} aria-label="Close import and parse story" className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-white/10 transition-colors">
                                <X size={20} />
                            </button>
                        </div>
                        
                        <div className="p-6 overflow-y-auto flex-1 flex flex-col gap-4">
                            <p className="text-sm text-gray-400">
                                Paste a story below. The AI will extract Characters, Locations, and Lorebooks.
                            </p>
                            <textarea
                                value={text}
                                onChange={(e) => setText(e.target.value)}
                                placeholder="Once upon a time in the city of..."
                                className="w-full flex-1 min-h-[200px] bg-gray-950/50 border border-gray-800 rounded-xl p-4 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-indigo-500/50 resize-none font-medium text-sm leading-relaxed"
                                disabled={isParsing}
                            />
                        </div>
                        
                        <div className="px-6 py-4 bg-gray-800/30 border-t border-gray-800 flex justify-end gap-3 shrink-0">
                            <button
                                onClick={onClose}
                                className="px-4 py-2 text-gray-400 hover:text-white font-medium transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => {
                                    if (text.trim()) {
                                        setIsParsing(true);
                                        onComplete(text).finally(() => setIsParsing(false));
                                    }
                                }}
                                disabled={isParsing || !text.trim()}
                                className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white rounded-lg font-medium transition-all"
                            >
                                {isParsing ? (
                                    <><Loader2 size={18} className="animate-spin" /> Processing...</>
                                ) : (
                                    <><Sparkles size={18} /> Parse & Import</>
                                )}
                            </button>
                        </div>
                    </motion.div>
                </>
            )}
        </AnimatePresence>
    );
}
