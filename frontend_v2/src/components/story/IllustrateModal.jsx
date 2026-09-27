import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ImageIcon } from 'lucide-react';
import { useEscapeKey } from '../../hooks/useEscapeKey';

export default React.memo(function IllustrateModal({ isOpen, prompt, onPromptChange, onConfirm, onClose }) {
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
                    onClick={onClose}
                >
                    <motion.div
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-md shadow-2xl"
                        onClick={e => e.stopPropagation()}
                    >
                        <h3 className="text-lg font-semibold text-gray-100 flex items-center gap-2 mb-4">
                            <ImageIcon size={18} className="text-amber-400" />
                            Generate Illustration
                        </h3>
                        <p className="text-sm text-gray-400 mb-4">
                            Optionally describe what you want to see, or leave blank for the AI to choose based on the chapter content.
                        </p>
                        <textarea
                            value={prompt}
                            onChange={e => onPromptChange(e.target.value)}
                            placeholder="e.g. A moonlit forest clearing with a mysterious figure... (optional)"
                            className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-amber-500/50 resize-none h-24 mb-4"
                            autoFocus
                        />
                        <div className="flex gap-2 justify-end">
                            <button
                                onClick={onClose}
                                className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={onConfirm}
                                className="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg hover:bg-amber-500 transition-colors flex items-center gap-2"
                            >
                                <ImageIcon size={14} />
                                Generate
                            </button>
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
});
