import React, { useState, useMemo } from 'react';
import { Users, Search, Check, X, UserPlus, Shield } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';
import { getAvatarUrl } from '../../hooks/useWorldVault';

export default function CompanionPickerModal({
    isOpen,
    onClose,
    characters = [],
    primaryCharacterId,
    additionalCharacterIds = [],
    onSave,
}) {
    const [selectedIds, setSelectedIds] = useState(() => new Set(additionalCharacterIds || []));
    const [searchQuery, setSearchQuery] = useState('');

    const filteredCharacters = useMemo(() => {
        const q = searchQuery.toLowerCase().trim();
        return characters.filter(c => {
            if (!q) return true;
            return (
                (c.name && c.name.toLowerCase().includes(q)) ||
                (c.tagline && c.tagline.toLowerCase().includes(q)) ||
                (c.persona && c.persona.toLowerCase().includes(q))
            );
        });
    }, [characters, searchQuery]);

    const handleToggle = (charId) => {
        if (charId === primaryCharacterId) return; // Primary character cannot be removed
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(charId)) {
                next.delete(charId);
            } else {
                next.add(charId);
            }
            return next;
        });
    };

    const handleConfirm = () => {
        onSave?.(Array.from(selectedIds));
        onClose();
    };

    if (!isOpen) return null;

    return (
        <ModalOverlay isOpen={isOpen} onClose={onClose} title="Manage Party Companions">
            <div className="p-4 sm:p-6 space-y-4">
                <div className="flex items-center justify-between pb-3 border-b border-white/5">
                    <div>
                        <h3 className="text-base font-semibold text-gray-100 flex items-center gap-2">
                            <Users size={18} className="text-blue-400" />
                            Group Chat Companions
                        </h3>
                        <p className="text-xs text-gray-400 mt-0.5">
                            Add characters to join this conversation and reply autonomously.
                        </p>
                    </div>
                </div>

                {/* Search Bar */}
                <div className="relative">
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search characters by name or tag..."
                        className="w-full px-3 py-2 pl-9 bg-gray-800/80 border border-white/10 rounded-xl text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                        autoFocus
                    />
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
                </div>

                {/* Character List Grid */}
                <div className="max-h-72 overflow-y-auto custom-scrollbar space-y-2 pr-1">
                    {filteredCharacters.length === 0 ? (
                        <div className="p-6 text-center text-xs text-gray-500">
                            No characters match your search.
                        </div>
                    ) : (
                        filteredCharacters.map((char) => {
                            const isPrimary = char.id === primaryCharacterId;
                            const isSelected = isPrimary || selectedIds.has(char.id);

                            return (
                                <div
                                    key={char.id}
                                    onClick={() => !isPrimary && handleToggle(char.id)}
                                    className={`flex items-center justify-between p-2.5 rounded-xl border transition-all ${
                                        isPrimary
                                            ? 'bg-blue-500/10 border-blue-500/30 cursor-default'
                                            : isSelected
                                                ? 'bg-purple-500/15 border-purple-500/40 cursor-pointer hover:bg-purple-500/20'
                                                : 'bg-gray-800/40 border-white/5 cursor-pointer hover:bg-gray-800/80 hover:border-white/10'
                                    }`}
                                >
                                    <div className="flex items-center gap-3 min-w-0 flex-1">
                                        <div className="w-9 h-9 rounded-full bg-gray-800 border border-white/10 overflow-hidden shrink-0 flex items-center justify-center">
                                            {char.avatar_path ? (
                                                <img
                                                    src={getAvatarUrl(char.id)}
                                                    alt={char.name}
                                                    className="w-full h-full object-cover"
                                                />
                                            ) : (
                                                <span className="text-xs font-bold text-gray-400">
                                                    {char.name?.charAt(0) || '?'}
                                                </span>
                                            )}
                                        </div>
                                        <div className="min-w-0 flex-1">
                                            <div className="flex items-center gap-1.5">
                                                <span className="text-xs font-medium text-gray-200 truncate">
                                                    {char.name}
                                                </span>
                                                {isPrimary && (
                                                    <span className="px-1.5 py-0.2 rounded bg-blue-500/20 text-blue-300 text-3xs font-semibold uppercase">
                                                        Primary
                                                    </span>
                                                )}
                                            </div>
                                            {char.tagline && (
                                                <p className="text-3xs text-gray-400 truncate">
                                                    {char.tagline}
                                                </p>
                                            )}
                                        </div>
                                    </div>

                                    <div className="shrink-0 ml-3">
                                        {isPrimary ? (
                                            <Shield size={16} className="text-blue-400" />
                                        ) : (
                                            <div
                                                className={`w-5 h-5 rounded-md border flex items-center justify-center transition-colors ${
                                                    isSelected
                                                        ? 'bg-purple-500 border-purple-500 text-white'
                                                        : 'border-white/20 bg-black/20'
                                                }`}
                                            >
                                                {isSelected && <Check size={12} strokeWidth={3} />}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })
                    )}
                </div>

                {/* Footer Controls */}
                <div className="flex items-center justify-between pt-3 border-t border-white/5 text-xs">
                    <span className="text-gray-400 text-3xs">
                        {selectedIds.size} companion{selectedIds.size === 1 ? '' : 's'} selected
                    </span>
                    <div className="flex items-center gap-2">
                        <button
                            type="button"
                            onClick={onClose}
                            className="px-3 py-1.5 rounded-lg text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
                        >
                            Cancel
                        </button>
                        <button
                            type="button"
                            onClick={handleConfirm}
                            className="px-4 py-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-medium shadow-md transition-all"
                        >
                            Update Party
                        </button>
                    </div>
                </div>
            </div>
        </ModalOverlay>
    );
}
