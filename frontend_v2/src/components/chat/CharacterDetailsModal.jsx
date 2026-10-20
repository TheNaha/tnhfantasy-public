import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { X, User, MessageSquare, ExternalLink } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';
import { QueryErrorState } from '../common/QueryState';
import { useChatsByCharacter } from '../../hooks/useChats';

function CharacterDetailsModal({ character, onClose }) {
    const navigate = useNavigate();
    // The character's own conversations. A character was a dead end: the
    // panel showed the description and nothing pointed anywhere, and there
    // was no list of the chats this character is in.
    const { data: chats = [], isLoading: chatsLoading, isError: chatsError, error: chatsErrorDetail, refetch: refetchChats } = useChatsByCharacter(character?.id);

    if (!character) return null;
    return (
        // The backdrop never closed this read-only panel, so keep
        // closeOnBackdrop={false}; Escape now does.
        <ModalOverlay onClose={onClose} closeOnBackdrop={false} className="z-50 bg-black/70 backdrop-blur-sm">
            <motion.div
                role="dialog"
                aria-modal="true"
                aria-label={character.name}
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="w-full max-w-2xl bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                    <h3 className="font-bold text-gray-100 flex items-center gap-2">
                        <User size={16} className="text-blue-400" />
                        {character.name}
                    </h3>
                    <div className="flex items-center gap-1">
                        <button
                            type="button"
                            onClick={() => navigate(`/characters`)}
                            className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-gray-400 hover:text-white rounded-xl hover:bg-white/5 transition-colors"
                            title="Open the character in the vault"
                        >
                            <ExternalLink size={13} />
                            Character page
                        </button>
                        <button onClick={onClose} aria-label="Close character details" className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                            <X size={18} />
                        </button>
                    </div>
                </div>

                <div className="p-6 overflow-y-auto custom-scrollbar space-y-6">
                    {character.description && (
                        <div>
                            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Description</h4>
                            <div className="bg-gray-800/50 rounded-xl p-4 text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {character.description}
                            </div>
                        </div>
                    )}
                    {character.personality && (
                        <div>
                            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Personality</h4>
                            <div className="bg-gray-800/50 rounded-xl p-4 text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {character.personality}
                            </div>
                        </div>
                    )}
                    {character.scenario && (
                        <div>
                            <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Scenario</h4>
                            <div className="bg-gray-800/50 rounded-xl p-4 text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">
                                {character.scenario}
                            </div>
                        </div>
                    )}
                    {(!character.description && !character.personality && !character.scenario) && (
                        <p className="text-gray-500 italic text-center py-4">No detailed information available.</p>
                    )}

                    <div>
                        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-2">Conversations</h4>
                        {chatsLoading ? (
                            <p className="text-sm text-gray-500">Loading…</p>
                        ) : chatsError ? (
                            <QueryErrorState
                                noun="chats"
                                error={chatsErrorDetail || chatsError}
                                onRetry={refetchChats}
                                className="border-slate-500/30 bg-slate-500/10"
                            />
                        ) : chats.length === 0 ? (
                            <p className="text-sm text-gray-500 italic">No conversations with this character yet.</p>
                        ) : (
                            <ul className="space-y-1.5">
                                {chats.map((chat) => (
                                    <li key={chat.id}>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                onClose?.();
                                                navigate(`/chat/${chat.id}`);
                                            }}
                                            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-xl bg-gray-800/50 hover:bg-gray-700/60 text-left transition-colors"
                                        >
                                            <MessageSquare size={13} className="text-blue-400 shrink-0" />
                                            <span className="text-sm text-gray-300 truncate flex-1">
                                                {chat.name || 'Untitled chat'}
                                            </span>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </div>
            </motion.div>
        </ModalOverlay>
    );
}

export default CharacterDetailsModal;
