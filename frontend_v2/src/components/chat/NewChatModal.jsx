import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { X, Check } from 'lucide-react';
import ModalOverlay from '../common/ModalOverlay';

const CUSTOM_PERSONA = '__custom__';
const CUSTOM_LOCATION = '__custom__';

// `locations` is a prop, like every other input here, rather than a
// `useLocations()` call inside the wizard. The wizard is presentational and its
// caller already has to supply characters, lorebooks, personas and worlds; a
// data hook here meant every renderer of this modal needed a QueryClient it
// otherwise had no reason to have.
function NewChatModal({ characters, lorebooks, locations = [], personas = [], worlds = [], onCreate, onClose }) {
    const [selectedCharacter, setSelectedCharacter] = useState(null);
    const [selectedLorebooks, setSelectedLorebooks] = useState([]);
    const [chatName, setChatName] = useState('New Chat');
    const [personaChoice, setPersonaChoice] = useState('');
    const [personaName, setPersonaName] = useState('');
    const [worldId, setWorldId] = useState('');
    const [storyTime, setStoryTime] = useState('');
    const [locationChoice, setLocationChoice] = useState('');
    const [customLocation, setCustomLocation] = useState('');
    const [isCreating, setIsCreating] = useState(false);
    const [step, setStep] = useState(0);

    const selectedLocation = locations.find(l => l.id === locationChoice) || null;

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
                setLocationChoice(CUSTOM_LOCATION);
                setCustomLocation(selectedCharacter.default_location);
            } else if (scenario.toLowerCase().includes('tavern')) {
                setLocationChoice(CUSTOM_LOCATION);
                setCustomLocation('Tavern');
            } else if (scenario.toLowerCase().includes('castle')) {
                setLocationChoice(CUSTOM_LOCATION);
                setCustomLocation('Castle');
            } else if (scenario.toLowerCase().includes('forest')) {
                setLocationChoice(CUSTOM_LOCATION);
                setCustomLocation('Forest');
            } else if (scenario.toLowerCase().includes('city')) {
                setLocationChoice(CUSTOM_LOCATION);
                setCustomLocation('City');
            } else {
                setLocationChoice('');
                setCustomLocation('');
            }
        } else {
            setChatName('New Chat');
            setStoryTime('');
            setLocationChoice('');
            setCustomLocation('');
        }
    }, [selectedCharacter]);

    const toggleLorebook = (id) => {
        if (selectedLorebooks.includes(id)) {
            setSelectedLorebooks(selectedLorebooks.filter(l => l !== id));
        } else {
            setSelectedLorebooks([...selectedLorebooks, id]);
        }
    };

    // The server resolves `persona_name = persona_name or persona.name`, so a
    // typed name silently wins while the library persona's description is still
    // inherited. The two controls were side by side on this step with nothing
    // saying so. They are one control now: picking a library persona sets
    // `persona_id` and clears the name; picking "custom" does the reverse.
    const effectivePersonaId = personaChoice === CUSTOM_PERSONA ? '' : personaChoice;
    const effectivePersonaName = personaChoice === CUSTOM_PERSONA ? personaName.trim() : '';

    // One location, two columns. `location_id` is what injects the location's
    // description, atmosphere and tags; `story_location` is the free text that
    // becomes the prompt's `Current Location:` line and the only value the
    // Activity page's location filter can match. Picking a library location
    // writes both, so the two stop disagreeing.
    const effectiveLocationId = locationChoice === CUSTOM_LOCATION ? '' : locationChoice;
    const effectiveStoryLocation = locationChoice === CUSTOM_LOCATION
        ? customLocation.trim()
        : (selectedLocation?.name || '');

    const handleCreate = async () => {
        if (isCreating) return;
        setIsCreating(true);
        try {
            await onCreate({
                chatName: chatName.trim() || 'New Chat',
                characterId: selectedCharacter?.id || null,
                personaName: effectivePersonaName || null,
                personaId: effectivePersonaId || null,
                worldId: worldId || null,
                storyTime,
                locationId: effectiveLocationId || null,
                storyLocation: effectiveStoryLocation || null,
                selectedLorebooks,
            });
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
                    <button onClick={onClose} aria-label="Close new chat" className="p-2 text-gray-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
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
                                <label htmlFor="new-chat-persona" className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Your Persona (Optional)</label>
                                <select
                                    id="new-chat-persona"
                                    data-testid="new-chat-persona-select"
                                    value={personaChoice}
                                    onChange={(e) => setPersonaChoice(e.target.value)}
                                    className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 appearance-none"
                                >
                                    <option value="">No persona — you are the default user</option>
                                    {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                    <option value={CUSTOM_PERSONA}>Custom name…</option>
                                </select>
                                {personaChoice === CUSTOM_PERSONA && (
                                    <input
                                        type="text"
                                        data-testid="new-chat-persona-name"
                                        value={personaName}
                                        onChange={(e) => setPersonaName(e.target.value)}
                                        className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/50"
                                        placeholder="e.g. Wanderer"
                                    />
                                )}
                                <p className="text-xs text-slate-500">
                                    A library persona supplies your name and description.
                                    Choosing <span className="text-slate-400">Custom name</span> clears the library link: your typed name wins,
                                    and the library persona&rsquo;s description still fills in if you have not written one of your own.
                                    Manage the library in <span className="text-cyan-300">Personas</span>, and edit either of them later from the chat&rsquo;s Context panel.
                                </p>
                            </div>
                        </>
                    )}

                    {step === 1 && (
                        <>
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Character (Optional)</label>
                                <select value={selectedCharacter?.id || ''} onChange={(e) => setSelectedCharacter(characters.find(c => c.id === e.target.value) || null)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 appearance-none"><option value="">No Character</option>{characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
                            </div>
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Time</label>
                                <input type="text" value={storyTime} onChange={(e) => setStoryTime(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200" placeholder="e.g. Day" />
                            </div>
                            <div className="space-y-2">
                                <label htmlFor="new-chat-location" className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Location (Optional)</label>
                                <select
                                    id="new-chat-location"
                                    data-testid="new-chat-location-select"
                                    value={locationChoice}
                                    onChange={(e) => setLocationChoice(e.target.value)}
                                    className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 appearance-none"
                                >
                                    <option value="">No location</option>
                                    {locations.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
                                    <option value={CUSTOM_LOCATION}>Custom / free text…</option>
                                </select>
                                {locationChoice === CUSTOM_LOCATION && (
                                    <input
                                        type="text"
                                        data-testid="new-chat-location-name"
                                        value={customLocation}
                                        onChange={(e) => setCustomLocation(e.target.value)}
                                        className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-500/50"
                                        placeholder="e.g. Tavern"
                                    />
                                )}
                                <p className="text-xs text-slate-500">
                                    A library location contributes its description, atmosphere and tags to every reply.
                                    Free text only contributes a name, so the two are not interchangeable.
                                </p>
                            </div>
                            {worlds.length > 0 && (
                            <div className="space-y-2">
                                <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider">World (Optional)</label>
                                <select aria-label="World" data-testid="new-chat-world-select" value={worldId} onChange={(e) => setWorldId(e.target.value)} className="w-full bg-gray-800/50 border border-white/10 rounded-xl px-4 py-3 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 appearance-none"><option value="">No World</option>{worlds.map(w => <option key={w.id} value={w.id}>{w.name}</option>)}</select>
                                <p className="text-xs text-slate-500">
                                    A world feeds its own lorebooks, locations and scenario into every reply.
                                    You can change or drop it later from the chat&rsquo;s <span className="text-cyan-300">Context &rarr; World</span> panel.
                                </p>
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
                            <div className="rounded-xl border border-white/10 bg-white/5 p-4 text-sm text-slate-300"><p className="font-medium text-white">{chatName || 'New Chat'}</p><p className="mt-1 text-xs text-slate-400">{selectedCharacter ? `Playing with ${selectedCharacter.name}` : 'No character selected'}{effectiveStoryLocation ? ` · ${effectiveStoryLocation}` : ''}</p></div>
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
