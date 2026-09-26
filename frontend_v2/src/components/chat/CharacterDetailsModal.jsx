import { motion } from 'framer-motion';
import { X, User } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';

function CharacterDetailsModal({ character, onClose }) {
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
                    <button onClick={onClose} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                        <X size={18} />
                    </button>
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
                </div>
            </motion.div>
        </ModalOverlay>
    );
}

export default CharacterDetailsModal;
