import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, User, Images, MessageSquare, ExternalLink, Grid, LayoutGrid, Filter } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useWorldVaultStore } from '../store/worldVaultStore';
import { useCharacters, useCharacterCollection, useCharacterCollections, getAvatarUrl } from '../hooks/useWorldVault';
import SceneGallery from '../components/SceneGallery';
import EmptyState from '../components/EmptyState';
import RoleplayPageShell from '../components/RoleplayPageShell';

const VIEW_MODES = {
    CARDS: 'cards',
    GRID: 'grid',
};

export default function AvatarGallery() {
    const [searchQuery, setSearchQuery] = useState('');
    const [viewMode, setViewMode] = useState(VIEW_MODES.CARDS);
    const [selectedCharacter, setSelectedCharacter] = useState(null);

    const { data: characters = [], isLoading } = useCharacters();
    const { data: characterCollections } = useCharacterCollections(characters.map(c => c.id));
    const navigate = useNavigate();
    const setActiveChatId = useWorldVaultStore((state) => state.setActiveChat);

    const filteredCharacters = useMemo(() => {
        if (!searchQuery.trim()) return characters;
        const q = searchQuery.toLowerCase();
        return characters.filter(c =>
            c.name?.toLowerCase().includes(q) ||
            c.description?.toLowerCase().includes(q) ||
            c.visual_tags?.some(t => t.toLowerCase().includes(q))
        );
    }, [characters, searchQuery]);

    const handleChat = (characterId) => {
        // ChatWorkspaceContext auto-creates (or reuses) a chat for this
        // character when /chat is entered with location.state.characterId.
        setActiveChatId(null);
        navigate('/chat', { state: { characterId } });
    };

    const handleCharacterClick = (characterId) => {
        navigate(`/characters#char-${characterId}`);
    };

    return (
        <RoleplayPageShell
            title="Character Avatar Gallery"
            description="Browse character avatars, scenes, and expression sheets"
            icon={Images}
            actions={
                <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 p-1">
                    <button
                        onClick={() => setViewMode(VIEW_MODES.CARDS)}
                        className={`rounded-md p-2 transition-colors ${viewMode === VIEW_MODES.CARDS ? 'bg-cyan-500/20 text-cyan-300' : 'text-gray-400 hover:text-white'}`}
                        title="Card view"
                    >
                        <LayoutGrid size={16} />
                    </button>
                    <button
                        onClick={() => setViewMode(VIEW_MODES.GRID)}
                        className={`rounded-md p-2 transition-colors ${viewMode === VIEW_MODES.GRID ? 'bg-cyan-500/20 text-cyan-300' : 'text-gray-400 hover:text-white'}`}
                        title="Grid view"
                    >
                        <Grid size={16} />
                    </button>
                </div>
            }
        >

            <div className="mb-6">
                <div className="relative max-w-md">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="Search characters..."
                        className="w-full pl-10 pr-4 py-2.5 bg-gray-800/60 border border-white/10 rounded-lg text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50"
                    />
                </div>
            </div>

            {isLoading ? (
                <div className="text-center py-12 text-gray-400">Loading characters...</div>
            ) : filteredCharacters.length === 0 ? (
                <EmptyState
                    icon={User}
                    title="No characters found"
                    description="Create some characters first to see them here."
                />
            ) : viewMode === VIEW_MODES.CARDS ? (
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                    {filteredCharacters.map((character) => (
                        <CharacterCard
                            key={character.id}
                            character={character}
                            collections={characterCollections}
                            onChat={handleChat}
                            onNavigateToCharacter={handleCharacterClick}
                        />
                    ))}
                </div>
            ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4">
                    {filteredCharacters.map((character) => (
                        <CharacterGridItem
                            key={character.id}
                            character={character}
                            collections={characterCollections}
                            onChat={handleChat}
                            onNavigateToCharacter={handleCharacterClick}
                        />
                    ))}
                </div>
            )}

            <AnimatePresence>
                {selectedCharacter && (
                    <SceneLightbox
                        character={selectedCharacter}
                        onClose={() => setSelectedCharacter(null)}
                    />
                )}
            </AnimatePresence>
        </RoleplayPageShell>
    );
}

function CharacterCard({ character, collections, onChat, onNavigateToCharacter }) {
    const collection = collections?.[character.id];
    const imageCount = collection?.image_count || 0;

    return (
        <motion.div
            layout
            className="glass-panel rounded-xl border border-white/5 p-5 hover:border-blue-500/30 transition-all group"
        >
            <div className="flex items-start gap-4">
                <div
                    className="w-16 h-16 rounded-xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 flex items-center justify-center shrink-0 overflow-hidden cursor-pointer"
                    onClick={() => onNavigateToCharacter(character.id)}
                >
                    {character.has_avatar ? (
                        <img src={getAvatarUrl(character.id)} alt={character.name} className="w-full h-full object-cover" />
                    ) : (
                        <User size={28} className="text-gray-500" />
                    )}
                </div>
                <div className="flex-1 min-w-0">
                    <h3 className="font-semibold text-white truncate">{character.name}</h3>
                    {character.description && (
                        <p className="text-xs text-gray-400 mt-1 line-clamp-2">{character.description}</p>
                    )}
                    {character.personality && (
                        <p className="text-xs text-gray-500 mt-1.5 line-clamp-1 italic">"{character.personality}"</p>
                    )}
                </div>
            </div>

            {character.visual_tags?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-3">
                    {character.visual_tags.slice(0, 4).map((tag, idx) => (
                        <span key={idx} className="px-1.5 py-0.5 text-[10px] bg-purple-500/10 text-purple-400 rounded border border-purple-500/20">{tag}</span>
                    ))}
                    {character.visual_tags.length > 4 && (
                        <span className="px-1.5 py-0.5 text-[10px] text-gray-500">+{character.visual_tags.length - 4}</span>
                    )}
                </div>
            )}

            {imageCount > 0 && (
                <div className="mt-4">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-xs text-gray-400 font-medium">Scenes ({imageCount})</span>
                    </div>
                    <div className="max-h-32 overflow-hidden rounded-lg">
                        <SceneGallery images={collection?.images?.slice(0, 8) || []} compact />
                    </div>
                </div>
            )}

            <div className="flex items-center gap-2 mt-4 pt-4 border-t border-white/5">
                    <button
                        onClick={() => onChat(character.id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-500/20 text-blue-300 rounded-lg hover:bg-blue-500/30 transition-colors"
                    >
                    <MessageSquare size={14} /> Chat
                </button>
                <button
                    onClick={() => onNavigateToCharacter(character.id)}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/5 text-gray-400 rounded-lg hover:bg-white/10 hover:text-white transition-colors ml-auto"
                >
                    <ExternalLink size={14} /> View
                </button>
            </div>
        </motion.div>
    );
}

function CharacterGridItem({ character, collections, onNavigateToCharacter }) {
    const collection = collections?.[character.id];

    return (
        <motion.div
            layout
            className="glass-panel rounded-xl border border-white/5 overflow-hidden hover:border-blue-500/30 transition-all group cursor-pointer"
            onClick={() => onNavigateToCharacter(character.id)}
        >
            <div className="aspect-square bg-gray-800/50 relative">
                {character.has_avatar ? (
                    <img src={getAvatarUrl(character.id)} alt={character.name} className="w-full h-full object-cover" />
                ) : (
                    <div className="w-full h-full flex items-center justify-center">
                        <User size={32} className="text-gray-600" />
                    </div>
                )}
                {collection?.image_count > 0 && (
                    <div className="absolute top-2 right-2 bg-black/60 text-white text-[10px] px-2 py-0.5 rounded-full flex items-center gap-1">
                        <Images size={10} /> {collection.image_count}
                    </div>
                )}
            </div>
            <div className="p-3">
                <h3 className="font-medium text-white text-sm truncate">{character.name}</h3>
                {character.description && (
                    <p className="text-xs text-gray-400 mt-0.5 line-clamp-1">{character.description}</p>
                )}
            </div>
        </motion.div>
    );
}

function SceneLightbox({ character, onClose }) {
    const { data: collection } = useCharacterCollection(character.id);
    const [currentIdx, setCurrentIdx] = useState(0);

    const images = collection?.images || [];
    const currentImage = images[currentIdx];

    const goNext = () => setCurrentIdx(i => (i + 1) % images.length);
    const goPrev = () => setCurrentIdx(i => (i - 1 + images.length) % images.length);

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/90 backdrop-blur-sm z-50 flex items-center justify-center p-4"
            onClick={onClose}
        >
            <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                className="bg-gray-900 border border-white/10 rounded-2xl p-6 w-full max-w-4xl shadow-2xl"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-white">{character.name} — Scenes</h2>
                    <button onClick={onClose} className="text-gray-400 hover:text-white">
                        <ExternalLink size={20} />
                    </button>
                </div>
                {images.length === 0 ? (
                    <div className="text-center py-10 text-gray-400">No scene images yet</div>
                ) : (
                    <div className="relative">
                        <div className="aspect-video bg-gray-800 rounded-xl overflow-hidden">
                            <img src={currentImage} alt="" className="w-full h-full object-contain" />
                        </div>
                        {images.length > 1 && (
                            <>
                                <button
                                    onClick={goPrev}
                                    className="absolute left-4 top-1/2 -translate-y-1/2 p-2 bg-black/50 text-white rounded-full hover:bg-black/70"
                                >
                                    ←
                                </button>
                                <button
                                    onClick={goNext}
                                    className="absolute right-4 top-1/2 -translate-y-1/2 p-2 bg-black/50 text-white rounded-full hover:bg-black/70"
                                >
                                    →
                                </button>
                                <div className="text-center mt-2 text-xs text-gray-400">
                                    {currentIdx + 1} / {images.length}
                                </div>
                            </>
                        )}
                    </div>
                )}
            </motion.div>
        </motion.div>
    );
}
