import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, Check } from 'lucide-react';

function NewChatModal({ characters, lorebooks, personas = [], onCreate, onClose }) {
    const [selectedCharacter, setSelectedCharacter] = useState(null);
    const [selectedLorebooks, setSelectedLorebooks] = useState([]);
    const [chatName, setChatName] = useState('New Chat');
    const [personaName, setPersonaName] = useState('');
    const [selectedPersonaId, setSelectedPersonaId] = useState('');
    const [storyTime, setStoryTime] = useState('');
    const [storyLocation, setStoryLocation] = useState('');
    const [isCreating, setIsCreating] = useState(false);

    useEffect(() => {
        if (selectedCharacter) {
            setChatName(`Chat with ${selectedCharacter.name}`);
            
            // Basic heuristic to suggest time/location
            const scenario = selectedCharacter.scenario || '';
            
            if (selectedCharacter.default_time) {
                setStoryTime(selectedCharacter.default_time);
            } else if (scenario.toLowerCase().includes('night') || scenario.toLowerCase().includes('evening')) {
                setStoryTime('Night');
            } else if (scenario.toLowerCase().includes('morning') || scenario.toLowerCase().includes('day')) {
                setStoryTime('Morning');
            } else {
                setStoryTime('');
            }
            
            if (selectedCharacter.default_location) {
                setStoryLocation(selectedCharacter.default_location);
            } else if (scenario.toLowerCase().includes('tavern')) {
                setStoryLocation('Tavern');
            } else if (scenario.toLowerCase().includes('castle')) {
                setStoryLocation('Castle');
            } else if (scenario.toLowerCase().includes('forest')) {
                setStoryLocation('Forest');
            } else if (scenario.toLowerCase().includes('city')) {
                setStoryLocation('City');
            } else {
                setStoryLocation('');
            }
        } else {
            setChatName('New Chat');
            setStoryTime('');
            setStoryLocation('');
        }
    }, [selectedCharacter]);

    const toggleLorebook = (id) => {
        if (selectedLorebooks.includes(id)) {
            setSelectedLorebooks(selectedLorebooks.filter(l => l !== id));
        } else {
            setSelectedLorebooks([...selectedLorebooks, id]);
        }
    };

    const handleCreate = async () => {
        if (isCreating) return;
        setIsCreating(true);
        try {
            await onCreate({ chatName: chatName.trim() || 'New Chat', characterId: selectedCharacter?.id || null, personaName: personaName.trim() || null, personaId: selectedPersonaId || null, storyTime, storyLocation, selectedLorebooks });
        } finally {
            setIsCreating(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
            <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="w-full max-w-lg bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                    <h3 className="font-bold text-gray-100">Create New Chat</h3>
                    <button onClick={onClose} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                        <X size={18} />
                    </button>
                </div>
                
                <div className="p-6 space-y-6 overflow-y-auto custom-scrollbar">
                    {/* Chat Name */}
                    <div className="space-y-2">
                        <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Chat Name</label>
                        <input
                            type="text"
                            value={chatName}
                            onChange={(e) => setChatName(e.target.value)}
                            className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-colors"
                            placeholder="e.g. Tavern Encounter"
                        />
                    </div>
                    
                    {/* Persona Name */}
                    <div className="space-y-2">
                        <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Your Persona (Optional)</label>
                        <input
                            type="text"
                            value={personaName}
                            onChange={(e) => setPersonaName(e.target.value)}
                            className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500/50 transition-colors"
                            placeholder="e.g. Wanderer"
                        />
                        {personas.length > 0 && (
                            <select
                                data-testid="new-chat-persona-select"
                                value={selectedPersonaId}
                                onChange={(e) => setSelectedPersonaId(e.target.value)}
                                className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:border-blue-500/50 transition-colors appearance-none"
                            >
                                <option value="">Library persona: none</option>
                                {personas.map(p => (
                                    <option key={p.id} value={p.id}>{p.name}</option>
                                ))}
                            </select>
                        )}
                    </div>

                    <div className="space-y-2">
                        <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Character (Optional)</label>
                        <select
                            value={selectedCharacter?.id || ''}
                            onChange={(e) => setSelectedCharacter(characters.find(c => c.id === e.target.value) || null)}
                            className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:border-blue-500/50 transition-colors appearance-none"
                        >
                            <option value="">No Character</option>
                            {characters.map(c => (
                                <option key={c.id} value={c.id}>{c.name}</option>
                            ))}
                        </select>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-3">
                         <div className="space-y-2">
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Time</label>
                            <input type="text" value={storyTime} onChange={(e) => setStoryTime(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200" placeholder="e.g. Day" />
                         </div>
                         <div className="space-y-2">
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Location</label>
                            <input type="text" value={storyLocation} onChange={(e) => setStoryLocation(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200" placeholder="e.g. Tavern" />
                         </div>
                    </div>

                    {lorebooks.length > 0 && (
                        <div className="space-y-2">
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Context Lorebooks</label>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                {lorebooks.map(lb => {
                                    const isActive = selectedLorebooks.includes(lb.id);
                                    return (
                                        <button
                                            key={lb.id}
                                            onClick={() => toggleLorebook(lb.id)}
                                            className={`text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors border ${isActive ? "bg-blue-500/20 text-blue-300 border-blue-500/30" : "bg-gray-800/30 text-gray-400 hover:bg-white/5 border-transparent"}`}
                                        >
                                            {isActive ? <Check size={14} className="text-blue-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}
                                            <span className="truncate">{lb.name}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>

                <div className="p-4 border-t border-white/5 bg-gray-900/60 shrink-0 flex justify-end gap-3">
                    <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-gray-400 hover:text-white transition-colors">
                        Cancel
                    </button>
                    <button 
                        onClick={handleCreate}
                        disabled={isCreating}
                        className="px-5 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white rounded-xl transition-all shadow-lg disabled:opacity-50"
                    >
                        Create
                    </button>
                </div>
            </motion.div>
        </div>
    );
}

export default NewChatModal;
