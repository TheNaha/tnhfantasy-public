import React from 'react';

export default React.memo(function CreateStoryModal({ title, onTitleChange, onConfirm, onClose }) {
    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
            onClick={onClose}
        >
            <div
                className="glass-panel p-6 rounded-2xl border border-white/10 w-full max-w-sm mx-4 space-y-4"
                onClick={(e) => e.stopPropagation()}
            >
                <h3 className="text-lg font-bold text-white">Create Story</h3>
                <input
                    autoFocus
                    type="text"
                    value={title}
                    onChange={(e) => onTitleChange(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') onConfirm(); }}
                    placeholder="Story title..."
                    className="w-full bg-gray-800/50 border border-gray-700/50 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                />
                <div className="flex justify-end gap-2">
                    <button
                        onClick={onClose}
                        className="px-4 py-2 text-sm rounded-lg text-gray-400 hover:bg-white/10 transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={onConfirm}
                        disabled={!title.trim()}
                        className="px-4 py-2 text-sm rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white transition-colors disabled:opacity-40"
                    >
                        Create
                    </button>
                </div>
            </div>
        </div>
    );
});
