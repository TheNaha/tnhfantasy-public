import { motion, AnimatePresence } from 'framer-motion';
import { Download, Star, Plus, X, Trash2 } from 'lucide-react';
import toast from 'react-hot-toast';

export default function SelectionToolbar({
    selectedFiles,
    onDownload,
    onDelete,
    onFavorite,
    onAddToCollection,
    onRemoveFromCollection,
    onCancel,
    activeCollection,
    favorites = []
}) {
    const hasSelection = selectedFiles.size > 0;

    return (
        <AnimatePresence>
            <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="flex items-center gap-2 p-3 bg-blue-900/20 border border-blue-500/30 rounded-lg flex-wrap"
            >
                <span className="text-sm text-blue-300 font-medium">
                    {selectedFiles.size} selected
                </span>

                <div className="h-4 w-px bg-blue-500/30" />

                <button
                    onClick={onDownload}
                    className="px-3 py-1.5 bg-blue-600 rounded-lg text-sm font-medium hover:bg-blue-500 flex items-center gap-2 transition-colors"
                    disabled={!hasSelection}
                >
                    <Download size={14} aria-hidden="true" />
                    Download
                </button>

                <button
                    onClick={onFavorite}
                    className="px-3 py-1.5 bg-yellow-600 rounded-lg text-sm font-medium hover:bg-yellow-500 flex items-center gap-2 transition-colors"
                    disabled={!hasSelection}
                >
                    <Star size={14} aria-hidden="true" />
                    <span className="hidden sm:inline">Add to Favorites</span>
                    <span className="sm:hidden">Favorite</span>
                </button>

                <button
                    onClick={onAddToCollection}
                    className="px-3 py-1.5 bg-purple-600 rounded-lg text-sm font-medium hover:bg-purple-500 flex items-center gap-2 transition-colors"
                    disabled={!hasSelection}
                >
                    <Plus size={14} aria-hidden="true" />
                    <span className="hidden sm:inline">Add to Collection</span>
                    <span className="sm:hidden">Collection</span>
                </button>

                {activeCollection && (
                    <button
                        onClick={onRemoveFromCollection}
                        className="px-3 py-1.5 bg-orange-600 rounded-lg text-sm font-medium hover:bg-orange-500 flex items-center gap-2 transition-colors"
                        disabled={!hasSelection}
                    >
                        <X size={14} aria-hidden="true" />
                        <span className="hidden sm:inline">Remove from Collection</span>
                        <span className="sm:hidden">Remove</span>
                    </button>
                )}

                <button
                    onClick={onDelete}
                    className="px-3 py-1.5 bg-red-600 rounded-lg text-sm font-medium hover:bg-red-500 flex items-center gap-2 transition-colors"
                    disabled={!hasSelection}
                >
                    <Trash2 size={14} aria-hidden="true" />
                    Delete
                </button>

                <div className="flex-1" />

                <button
                    onClick={onCancel}
                    className="px-3 py-1.5 bg-gray-700 rounded-lg text-sm font-medium hover:bg-gray-600 text-gray-300 transition-colors"
                >
                    Cancel
                </button>
            </motion.div>
        </AnimatePresence>
    );
}
