import { X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const KeyboardShortcutsModal = ({ isOpen, onClose }) => {
    const shortcuts = {
        'Navigation': [
            { keys: ['D'], description: 'Go to Dashboard' },
            { keys: ['G'], description: 'Go to Generator' },
            { keys: ['M'], description: 'Go to Models' },
            { keys: ['A'], description: 'Go to Advanced' },
            { keys: ['⌘', 'K'], description: 'Open command palette' },
        ],
        'Actions': [
            { keys: ['?'], description: 'Show this help' },
            { keys: ['Esc'], description: 'Close modals' },
            { keys: ['S'], description: 'Toggle selection mode' },
            { keys: ['R'], description: 'Refresh gallery' },
            { keys: ['⌘', '⇧', 'Enter'], description: 'Send message' },
            { keys: ['Ctrl', 'N'], description: 'New chat' },
            { keys: ['Ctrl', 'S'], description: 'Save chapter' },
            { keys: ['Ctrl', '⇧', 'C'], description: 'Copy chapter content' },
        ],
        'Gallery': [
            { keys: ['←', '→'], description: 'Navigate images' },
            { keys: ['Space'], description: 'Open/close image' },
            { keys: ['Del'], description: 'Delete selected' },
            { keys: ['Ctrl', 'A'], description: 'Select all' },
        ],
    };

    return (
        <>
            {isOpen && (
            <AnimatePresence>
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80"
                    onClick={onClose}
                >
                    <motion.div
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ duration: 0.2 }}
                        onClick={(e) => e.stopPropagation()}
                        className="glass rounded-2xl w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col"
                    >
                        {/* Header */}
                        <div className="p-6 border-b border-gray-700/50">
                            <div className="flex items-center justify-between">
                                <div>
                                    <h2 className="text-2xl font-bold text-white mb-1">
                                        Keyboard Shortcuts
                                    </h2>
                                    <p className="text-sm text-gray-400">
                                        Boost your productivity with these hotkeys
                                    </p>
                                </div>
                                <button
                                    onClick={onClose}
                                    className="p-2 hover:bg-gray-700/50 rounded-full text-gray-400 hover:text-white transition-colors"
                                    aria-label="Close"
                                >
                                    <X size={24} />
                                </button>
                            </div>
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-y-auto p-6 space-y-4 md:space-y-8">
                            {Object.entries(shortcuts).map(([category, items]) => (
                                <div key={category}>
                                    <h3 className="text-sm font-bold text-gray-500 uppercase tracking-wider mb-4">
                                        {category}
                                    </h3>
                                    <div className="space-y-3">
                                        {items.map((shortcut, idx) => (
                                            <div
                                                key={idx}
                                                className="flex items-center justify-between p-3 rounded-lg bg-gray-800/50 hover:bg-gray-800 transition-colors"
                                            >
                                                <span className="text-sm text-gray-300">
                                                    {shortcut.description}
                                                </span>
                                                <div className="flex gap-2">
                                                    {shortcut.keys.map((key, keyIdx) => (
                                                        <kbd
                                                            key={keyIdx}
                                                            className="px-3 py-1.5 text-sm font-mono font-semibold bg-gray-900 text-white rounded-md border border-gray-700 shadow-sm min-w-[2.5rem] text-center"
                                                        >
                                                            {key}
                                                        </kbd>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>

                        {/* Footer */}
                        <div className="p-6 border-t border-gray-700/50 bg-gray-900/50">
                            <p className="text-xs text-gray-500 text-center">
                                Press{' '}
                                <kbd className="px-2 py-1 text-xs font-mono bg-gray-800 rounded border border-gray-700">
                                    ?
                                </kbd>{' '}
                                anytime to show this dialog
                            </p>
                        </div>
                    </motion.div>
                </div>
            </AnimatePresence>
            )}
        </>
    );
};

export default KeyboardShortcutsModal;
