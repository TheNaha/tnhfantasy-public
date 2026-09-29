import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, Check } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';

function NewChatModal({ characters, lorebooks, personas = [], worlds = [], onCreate, onClose }) {
    const [selectedCharacter, setSelectedCharacter] = useState(null);
    const [selectedLorebooks, setSelectedLorebooks] = useState([]);
    const [chatName, setChatName] = useState('New Chat');
    const [personaName, setPersonaName] = useState('');
    const [selectedPersonaId, setSelectedPersonaId] = useState('');
    const [worldId, setWorldId] = useState('');
    const [storyTime, setStoryTime] = useState('');
    const [storyLocation, setStoryLocation] = useState('');
    const [isCreating, setIsCreating] = useState(false);
    const [step, setStep] = useState(0);

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
            await onCreate({ chatName: chatName.trim() || 'New Chat', characterId: selectedCharacter?.id || null, personaName: personaName.trim() || null, personaId: selectedPersonaId || null, worldId: worldId || null, storyTime, storyLocation, selectedLorebooks });
        } finally {
            setIsCreating(false);
        }
    };

    return (
        // The backdrop never closed the wizard, so keep
        // closeOnBackdrop={false} — dismissing a half-filled chat by a stray
        // click was never possible. Escape now does.
        <ModalOverlay onClose={onClose} closeOnBackdrop={false} className="z-50 bg-black/70 backdrop-blur-sm">
            <motion.div
                role="dialog"
                aria-modal="true"
                aria-labelledby="new-chat-title"
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                className="w-full max-w-lg bg-gray-900 border border-white/10 rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-white/5 shrink-0">
                    <h3 id="new-chat-title" className="font-bold text-gray-100">Create New Chat</h3>
                    <button onClick={onClose} className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                        <X size={18} />
                    </button>
                </div>
                
                <div className="flex items-center gap-2 border-b border-white/5 px-6 py-3 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                    {['Basics', 'Cast & scene', 'Context'].map((label, index) => (
                        <div key={label} className="flex flex-1 items-center gap-2 last:flex-none">
                            <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${index <= step ? 'bg-cyan-500 text-slate-950' : 'bg-white/10 text-slate-500'}`}>{index + 1}</span>
                            <span className={index === step ? 'text-cyan-300' : 'hidden sm:inline'}>{label}</span>
                            {index < 2 && <span className="h-px flex-1 bg-white/10" />}
                        </div>
                    ))}
                </div>

                <div className="p-6 space-y-6 overflow-y-auto custom-scrollbar">
                    {step === 0 && (
                        <>
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Chat Name</label>
                                <input type="text" value={chatName} onChange={(e) => setChatName(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" placeholder="e.g. Tavern Encounter" />
                            </div>
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Your Persona (Optional)</label>
                                <input type="text" value={personaName} onChange={(e) => setPersonaName(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/50" placeholder="e.g. Wanderer" />
                                {personas.length > 0 && <select data-testid="new-chat-persona-select" value={selectedPersonaId} onChange={(e) => setSelectedPersonaId(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 appearance-none"><option value="">Library persona: none</option>{personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select>}
                            </div>
                        </>
                    )}

                    {step === 1 && (
                        <>
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Character (Optional)</label>
                                <select value={selectedCharacter?.id || ''} onChange={(e) => setSelectedCharacter(characters.find(c => c.id === e.target.value) || null)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 appearance-none"><option value="">No Character</option>{characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
                            </div>
                            <div className="grid grid-cols-2 gap-3">
                                <div className="space-y-2"><label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Time</label><input type="text" value={storyTime} onChange={(e) => setStoryTime(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200" placeholder="e.g. Day" /></div>
                                <div className="space-y-2"><label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Location</label><input type="text" value={storyLocation} onChange={(e) => setStoryLocation(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200" placeholder="e.g. Tavern" /></div>
                            </div>
                            {worlds.length > 0 && (
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">World (Optional)</label>
                                <select aria-label="World" value={worldId} onChange={(e) => setWorldId(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 appearance-none"><option value="">No World</option>{worlds.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</select>
                            </div>
                            )}
                        </>
                    )}

                    {step === 2 && (
                        <>
                            {lorebooks.length > 0 ? (
                                <div className="space-y-2">
                                    <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Context Lorebooks (Optional)</label>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">{lorebooks.map(lb => { const isActive = selectedLorebooks.includes(lb.id); return <button type="button" key={lb.id} onClick={() => toggleLorebook(lb.id)} className={`text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors border ${isActive ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30' : 'bg-gray-800/30 text-gray-400 hover:bg-white/5 border-transparent'}`}>{isActive ? <Check size={14} className="text-cyan-400 shrink-0" /> : <div className="w-3.5 h-3.5 rounded border border-gray-600 shrink-0" />}<span className="truncate">{lb.name}</span></button>; })}</div>
                                </div>
                            ) : <p className="text-sm text-slate-400">No lorebooks yet. You can add one later from the World page.</p>}
                            <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-slate-300"><p className="font-medium text-white">{chatName || 'New Chat'}</p><p className="mt-1 text-xs text-slate-400">{selectedCharacter ? `Playing with ${selectedCharacter.name}` : 'No character selected'}{storyLocation ? ` · ${storyLocation}` : ''}</p></div>
                        </>
                    )}
                </div>

                <div className="p-4 border-t border-white/5 bg-gray-900/60 shrink-0 flex items-center justify-between gap-3">
                    <button type="button" onClick={step === 0 ? onClose : () => setStep((value) => value - 1)} className="px-4 py-2 text-sm font-medium text-gray-400 hover:text-white transition-colors">{step === 0 ? 'Cancel' : 'Back'}</button>
                    {step < 2 ? <button type="button" onClick={() => setStep((value) => value + 1)} className="px-5 py-2 text-sm font-medium bg-cyan-500 hover:bg-cyan-400 text-slate-950 rounded-xl transition-all shadow-lg">Continue</button> : <button type="button" onClick={handleCreate} disabled={isCreating} className="px-5 py-2 text-sm font-medium bg-cyan-500 hover:bg-cyan-400 text-slate-950 rounded-xl transition-all shadow-lg disabled:opacity-50">{isCreating ? 'Creating…' : 'Create chat'}</button>}
                </div>
            </motion.div>
        </ModalOverlay>
    );
}

export default NewChatModal;
