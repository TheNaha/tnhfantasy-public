import { useState } from 'react';
import { FolderOpen, Plus, Trash2, Edit2, X, Check } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import useStore from '../../store/useStore';
import {
    useCollections,
    useCreateCollection,
    useDeleteCollection,
    useRenameCollection
} from '../../hooks/useCollections';
import CreateCollectionModal from './CreateCollectionModal';
import { useConfirmation } from '../../store/confirmationStore';
import { assetUrl } from '../../utils/assetUrl';
import EmptyState from '../EmptyState';

const CollectionsPanel = ({ isOpen, onClose }) => {
    console.log('DBGPANEL render isOpen=', isOpen);
    const { data: collections = {} } = useCollections();
    const activeCollection = useStore((state) => state.activeCollection);
    const setActiveCollection = useStore((state) => state.setActiveCollection);

    const createCollectionMutation = useCreateCollection();
    const deleteCollectionMutation = useDeleteCollection();
    const renameCollectionMutation = useRenameCollection();

    const [showCreateModal, setShowCreateModal] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [editName, setEditName] = useState('');
    const { confirm } = useConfirmation();

    const collectionList = Object.values(collections);
    const getImageCount = (collection) => collection.imageCount ?? collection.images?.length ?? 0;

    const handleCreate = (name, color) => {
        createCollectionMutation.mutate({ name, color });
    };

    const handleDelete = async (id, e) => {
        e.stopPropagation();
        const accepted = await confirm({
            title: 'Delete Collection?',
            message: 'This will delete the collection but keep all the images. This action cannot be undone.',
            confirmText: 'Delete Collection',
            isDangerous: true,
        });
        if (accepted) {
            deleteCollectionMutation.mutate(id);
        }
    };

    const handleRename = (id) => {
        if (editName.trim()) {
            renameCollectionMutation.mutate({ id, name: editName.trim() });
        }
        setEditingId(null);
        setEditName('');
    };

    const startEdit = (collection, e) => {
        e.stopPropagation();
        setEditingId(collection.id);
        setEditName(collection.name);
    };

    return (
        <>
            {isOpen && (
                <AnimatePresence>
                <div
                    key="collections-panel"
                    className="fixed inset-0 z-40 flex items-start justify-end bg-black/50"
                    onClick={onClose}
                >
                    <motion.div
                        initial={{ x: '100%' }}
                        animate={{ x: 0 }}
                        exit={{ x: '100%' }}
                        transition={{ type: 'tween', duration: 0.2, ease: 'easeOut' }}
                        onClick={(e) => e.stopPropagation()}
                        className="h-full w-full max-w-md bg-gray-900 border-l border-gray-800 flex flex-col shadow-2xl"
                    >
                        {/* Header */}
                        <div className="p-6 border-b border-gray-800">
                            <div className="flex items-center justify-between mb-4">
                                <div className="flex items-center gap-2">
                                    <FolderOpen className="text-blue-500" size={24} />
                                    <h2 className="text-xl font-bold text-white">Collections</h2>
                                </div>
                                <button
                                    onClick={onClose}
                                    className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white transition-colors"
                                    aria-label="Close collections panel"
                                    type="button"
                                >
                                    <X size={20} aria-hidden="true" />
                                </button>
                            </div>
                            <button
                                onClick={() => setShowCreateModal(true)}
                                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-colors"
                                aria-label="Create new collection"
                                type="button"
                            >
                                <Plus size={18} aria-hidden="true" />
                                New Collection
                            </button>
                        </div>

                        {/* Collections List */}
                        <div className="flex-1 overflow-y-auto p-4">
                            {collectionList.length === 0 ? (
                                <EmptyState
                                    type="collection"
                                    onAction={() => setShowCreateModal(true)}
                                />
                            ) : (
                                <div className="space-y-3">
                                    {/* All Images */}
                                    <button
                                        onClick={() => {
                                            setActiveCollection(null);
                                            onClose();
                                        }}
                                        className={`w-full p-4 rounded-lg border transition-all text-left ${!activeCollection
                                            ? 'bg-gray-800 border-blue-500'
                                            : 'bg-gray-800/50 border-gray-700 hover:border-gray-600'
                                            }`}
                                        aria-label="View all images"
                                        aria-pressed={!activeCollection}
                                    >
                                        <div className="flex items-center gap-3">
                                            <div className="w-10 h-10 rounded bg-gray-700 flex items-center justify-center">
                                                <FolderOpen size={20} className="text-gray-400" aria-hidden="true" />
                                            </div>
                                            <div>
                                                <div className="font-medium text-white">All Images</div>
                                                <div className="text-xs text-gray-500">View all</div>
                                            </div>
                                        </div>
                                    </button>

                                    {/* Collection List */}
                                    {collectionList.map((collection) => (
                                        <div
                                            key={collection.id}
                                            onClick={() => {
                                                setActiveCollection(collection.id);
                                                onClose();
                                            }}
                                            className={`group relative p-4 rounded-lg border transition-all cursor-pointer ${activeCollection === collection.id
                                                ? 'bg-gray-800 border-blue-500'
                                                : 'bg-gray-800/50 border-gray-700 hover:border-gray-600'
                                                }`}
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

                                                {/* Name */}
                                                <div className="flex-1 min-w-0">
                                                    {editingId === collection.id ? (
                                                        <input
                                                            type="text"
                                                            value={editName}
                                                            onChange={(e) => setEditName(e.target.value)}
                                                            onBlur={() => handleRename(collection.id)}
                                                            onKeyDown={(e) => {
                                                                if (e.key === 'Enter') handleRename(collection.id);
                                                                if (e.key === 'Escape') setEditingId(null);
                                                            }}
                                                            onClick={(e) => e.stopPropagation()}
                                                            className="w-full bg-gray-700 border border-gray-600 rounded px-2 py-1 text-sm text-white focus:ring-2 focus:ring-blue-500 outline-none"
                                                            autoFocus
                                                        />
                                                    ) : (
                                                        <>
                                                            <div className="font-medium text-white truncate">
                                                                {collection.name}
                                                            </div>
                                                            <div className="text-xs text-gray-500">
                                                                {getImageCount(collection)} image
                                                                {getImageCount(collection) !== 1 ? 's' : ''}
                                                            </div>
                                                        </>
                                                    )}
                                                </div>

                                                {/* Actions */}
                                                <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                    <button
                                                        onClick={(e) => startEdit(collection, e)}
                                                        className="p-1.5 hover:bg-gray-700 rounded text-gray-400 hover:text-white"
                                                        title="Rename"
                                                        aria-label={`Rename collection ${collection.name}`}
                                                    >
                                                        <Edit2 size={14} aria-hidden="true" />
                                                    </button>
                                                    <button
                                                        onClick={(e) => handleDelete(collection.id, e)}
                                                        className="p-1.5 hover:bg-red-900/50 rounded text-gray-400 hover:text-red-400"
                                                        title="Delete"
                                                        aria-label={`Delete collection ${collection.name}`}
                                                    >
                                                        <Trash2 size={14} aria-hidden="true" />
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </motion.div>

                    {/* Create Collection Modal */}
                    <CreateCollectionModal
                        isOpen={showCreateModal}
                        onClose={() => setShowCreateModal(false)}
                        onCreate={handleCreate}
                    />
                </div>
                </AnimatePresence>
            )}
        </>
    );
};

export default CollectionsPanel;
