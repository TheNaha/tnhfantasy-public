import { motion } from 'framer-motion';
import { X, ChevronRight } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';

function GreetingPickerModal({ character, onSelect, onClose }) {
    const greetings = [
        character.first_mes,
        ...(character.alternate_greetings || [])
    ].filter(Boolean);

    if (greetings.length <= 1) return null;

    return (
        // The backdrop never closed the picker, so keep
        // closeOnBackdrop={false}; Escape now does.
        <ModalOverlay onClose={onClose} closeOnBackdrop={false} className="z-50 items-end sm:items-center bg-black/70 backdrop-blur-sm">
            <motion.div
                role="dialog"
                aria-modal="true"
                aria-label="Choose opening"
                initial={{ y: '100%', opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                exit={{ y: '100%', opacity: 0 }}
                className="w-full max-w-lg bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden"
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5">
                    <div>
                        <h3 className="font-bold text-gray-100">Choose Opening</h3>
                        <p className="text-xs text-gray-500 mt-0.5">
                            {character.name} has {greetings.length} opening messages. Pick one to start the chat.
                        </p>
                    </div>
                    <button onClick={onClose} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                        <X size={18} />
                    </button>
                </div>
                <div className="p-4 space-y-3 max-h-[50vh] overflow-y-auto custom-scrollbar">
                    {greetings.map((greeting, idx) => (
                        <button
                            key={idx}
                            onClick={() => onSelect(greeting)}
                            className="w-full text-left p-4 rounded-xl bg-gray-800/50 border border-white/5 hover:border-blue-500/40 hover:bg-blue-500/5 transition-all text-sm text-gray-300 group"
                        >
                            <div className="flex items-start gap-3">
                                <span className="text-[10px] font-bold text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded shrink-0 mt-0.5">
                                    {idx === 0 ? 'Default' : `Alt ${idx}`}
                                </span>
                                <p className="line-clamp-3 leading-relaxed">{greeting}</p>
                                <ChevronRight size={16} className="text-gray-600 group-hover:text-blue-400 shrink-0 mt-0.5 transition-colors" />
                            </div>
                        </button>
                    ))}
                </div>
            </motion.div>
        </ModalOverlay>
    );
}

export default GreetingPickerModal;
