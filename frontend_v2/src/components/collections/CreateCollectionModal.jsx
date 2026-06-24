import { useState } from 'react';
import { X } from 'lucide-react';
import { motion as Motion, AnimatePresence } from 'framer-motion';
import { createPortal } from 'react-dom';

const CreateCollectionModal = ({ isOpen, onClose, onCreate }) => {
    const [name, setName] = useState('');
    const [color, setColor] = useState('#3B82F6');

    const colors = [
        '#3B82F6', // Blue
        '#8B5CF6', // Purple
        '#EC4899', // Pink
        '#EF4444', // Red
        '#F59E0B', // Amber
        '#10B981', // Green
        '#06B6D4', // Cyan
        '#6366F1', // Indigo
    ];

    const handleSubmit = (e) => {
        e.preventDefault();
        if (name.trim()) {
            onCreate(name.trim(), color);
            setName('');
            setColor('#3B82F6');
            onClose();
        }
    };

    return (
        <AnimatePresence>
            {isOpen && createPortal(
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80"
                    onClick={onClose}
                >
                    <Motion.div
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        exit={{ opacity: 0, scale: 0.9 }}
                        transition={{ duration: 0.2 }}
                        onClick={(e) => e.stopPropagation()}
                        className="glass rounded-2xl w-full max-w-md flex flex-col"
                    >
                        {/* Header */}
                        <div className="p-6 border-b border-gray-700/50">
                            <div className="flex items-center justify-between">
                                <h2 className="text-xl font-bold text-white">
                                    Create Collection
                                </h2>
                                <button
                                    onClick={onClose}
                                    className="p-2 hover:bg-gray-700/50 rounded-full text-gray-400 hover:text-white transition-colors"
                                    aria-label="Close modal"
                                >
                                    <X size={20} aria-hidden="true" />
                                </button>
                            </div>
                        </div>

                        {/* Content */}
                        <form onSubmit={handleSubmit} className="p-6 space-y-4 md:space-y-6">
                            {/* Name Input */}
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-2">
                                    Collection Name
                                </label>
                                <input
                                    type="text"
                                    value={name}
                                    onChange={(e) => setName(e.target.value)}
                                    placeholder="e.g., Best Portraits, Landscapes..."
                                    className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-2.5 text-white focus:ring-2 focus:ring-blue-500 outline-none"
                                    autoFocus
                                />
                            </div>

                            {/* Color Picker */}
                            <div>
                                <label className="block text-sm font-medium text-gray-400 mb-2">
                                    Color
                                </label>
                                <div className="grid grid-cols-8 gap-2">
                                    {colors.map((c) => (
                                        <button
                                            key={c}
                                            type="button"
                                            onClick={() => setColor(c)}
                                            className={`w-10 h-10 rounded-lg transition-all ${color === c
                                                    ? 'ring-2 ring-white ring-offset-2 ring-offset-gray-900 scale-110'
                                                    : 'hover:scale-105'
                                                }`}
                                            style={{ backgroundColor: c }}
                                            aria-label={`Select color ${c}`}
                                            aria-pressed={color === c}
                                        />
                                    ))}
                                </div>
                            </div>

                            {/* Actions */}
                            <div className="flex gap-3 pt-4">
                                <button
                                    type="button"
                                    onClick={onClose}
                                    className="flex-1 px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    disabled={!name.trim()}
                                    className="flex-1 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg font-medium transition-colors"
                                >
                                    Create
                                </button>
                            </div>
                        </form>
                    </Motion.div>
                </div>,
                document.body
            )}
        </AnimatePresence>
    );
};

export default CreateCollectionModal;
