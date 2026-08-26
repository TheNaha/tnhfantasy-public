import { X, FolderOpen } from 'lucide-react';
import { Modal } from '../common/Modal';
import { assetUrl } from '../../utils/assetUrl';

const SelectCollectionModal = ({ isOpen, onClose, collections, onSelect }) => {
    const collectionList = Object.values(collections);
    const getImageCount = (collection) => collection.imageCount ?? collection.images?.length ?? 0;

    if (collectionList.length === 0) {
        return null;
    }

    return (
        <Modal isOpen={isOpen} onClose={onClose} title="Select Collection">
            <p className="text-sm text-gray-400 px-6 pt-4">
                Choose which collection to add the selected images to
            </p>

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
                            aria-label={`Select collection ${collection.name}`}
                        >
                            <div className="flex items-center gap-3">
                                {/* Thumbnail or Icon */}
                                {collection.thumbnail ? (
                                    <img
                                        src={assetUrl(collection.thumbnail)}
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
                                        {getImageCount(collection)} image
                                        {getImageCount(collection) !== 1 ? 's' : ''}
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
        </Modal>
    );
};

export default SelectCollectionModal;
