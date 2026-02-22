import { X, FolderOpen } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const SelectCollectionModal = ({ isOpen, onClose, collections, onSelect }) => {
    const collectionList = Object.values(collections);

    if (collectionList.length === 0) {
        return null;
    }

    return (
        <AnimatePresence>
            {isOpen && (
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
                        className="glass rounded-2xl w-full max-w-md flex flex-col max-h-[70vh]"
                    >
                        {/* Header */}
                        <div className="p-6 border-b border-gray-700/50">
                            <div className="flex items-center justify-between">
                                <h2 className="text-xl font-bold text-white">
                                    Select Collection
                                </h2>
                                <button
                                    onClick={onClose}
                                    className="p-2 hover:bg-gray-700/50 rounded-full text-gray-400 hover:text-white transition-colors"
                                >
                                    <X size={20} />
                                </button>
                            </div>
                            <p className="text-sm text-gray-400 mt-2">
                                Choose which collection to add the selected images to
                            </p>
                        </div>

                        {/* Collections List */}
                        <div className="flex-1 overflow-y-auto p-4">
                            <div className="space-y-2">
                                {collectionList.map((collection) => (
                                    <button
                                        key={collection.id}
                                        onClick={() => {
                                            onSelect(collection.id);
                                            onClose();
                                        }}
                                        className="w-full p-4 rounded-lg border border-gray-700 hover:border-gray-600 bg-gray-800/50 hover:bg-gray-800 transition-all text-left group"
                                    >
                                        <div className="flex items-center gap-3">
                                            {/* Thumbnail or Icon */}
                                            {collection.thumbnail ? (
                                                <img
                                                    src={`/api/view/output/${collection.thumbnail}`}
                                                    alt={collection.name}
                                                    className="w-12 h-12 rounded object-cover"
                                                />
                                            ) : (
                                                <div
                                                    className="w-12 h-12 rounded flex items-center justify-center"
                                                    style={{ backgroundColor: `${collection.color}20` }}
                                                >
                                                    <FolderOpen
                                                        size={24}
                                                        style={{ color: collection.color }}
                                                    />
                                                </div>
                                            )}

                                            {/* Collection Info */}
                                            <div className="flex-1 min-w-0">
                                                <div className="font-medium text-white group-hover:text-blue-400 transition-colors truncate">
                                                    {collection.name}
                                                </div>
                                                <div className="text-xs text-gray-500">
                                                    {collection.images.length} image
                                                    {collection.images.length !== 1 ? 's' : ''}
                                                </div>
                                            </div>

                                            {/* Color Indicator */}
                                            <div
                                                className="w-3 h-3 rounded-full"
                                                style={{ backgroundColor: collection.color }}
                                            />
                                        </div>
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Footer */}
                        <div className="p-4 border-t border-gray-700/50">
                            <button
                                onClick={onClose}
                                className="w-full px-4 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-colors"
                            >
                                Cancel
                            </button>
                        </div>
                    </motion.div>
                </div>
            )}
        </AnimatePresence>
    );
};

export default SelectCollectionModal;
