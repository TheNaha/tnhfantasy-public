import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ImageIcon, X } from 'lucide-react';
import SceneGallery from '../SceneGallery';
import { useEscapeKey } from '../../hooks/useEscapeKey';

export default React.memo(function StoryGalleryModal({ isOpen, storyTitle, images, imagesError, onRetryImages, collectionsList, onSaveToCollection, onClose }) {
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
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
                    onClick={onClose}
                >
                    <motion.div
                        initial={{ scale: 0.95, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0.95, opacity: 0 }}
                        className="bg-gray-900 border border-white/10 rounded-3xl shadow-2xl w-full max-w-5xl flex flex-col h-[85vh] overflow-hidden"
                        onClick={e => e.stopPropagation()}
                    >
                        <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                            <h3 className="font-bold text-gray-100 flex items-center gap-2">
                                <ImageIcon size={16} className="text-indigo-400" />
                                {storyTitle || 'Story'} Gallery
                            </h3>
                            <button onClick={onClose} aria-label="Close story gallery" className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                                <X size={18} />
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                            <SceneGallery
                                title={`${storyTitle || 'Story'} gallery`}
                                images={images}
                                imagesError={imagesError}
                                onRetryImages={onRetryImages}
                                lightboxAction={(path) => (
                                    <select
                                        value=""
                                        onChange={(e) => {
                                            if (e.target.value) {
                                                onSaveToCollection(e.target.value, path);
                                                e.target.value = '';
                                            }
                                        }}
                                        className="bg-gray-800 border border-white/10 rounded-lg text-xs text-gray-200 px-2 py-1.5 cursor-pointer hover:border-indigo-500/40 transition-colors"
                                        title="Save to collection"
                                    >
                                        <option value="">Save to…</option>
                                        {collectionsList.map(c => (
                                            <option key={c.id} value={c.id}>{c.name}</option>
                                        ))}
                                    </select>
                                )}
                            />
                        </div>
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>
    );
});
