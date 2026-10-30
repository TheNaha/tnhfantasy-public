import { useState } from 'react';
import { X, Sparkles, Loader2, Smile } from 'lucide-react';
import toast from 'react-hot-toast';
// Through the API client, not bare fetch: a configured VITE_API_URL /
// localStorage API origin is ignored by a relative fetch, and only the client
// applies the 30s timeout.
import { api } from '../../api';

const DEFAULT_EMOTIONS = [
    { id: 'neutral', label: 'Neutral 😐' },
    { id: 'happy', label: 'Happy 😊' },
    { id: 'angry', label: 'Angry 😠' },
    { id: 'blushing', label: 'Blushing 😳' },
    { id: 'sad', label: 'Sad 😢' },
    { id: 'serious', label: 'Serious 🧐' },
];

export default function ExpressionStudioModal({ character, isOpen, onClose }) {
    const [selectedEmotions, setSelectedEmotions] = useState(DEFAULT_EMOTIONS.map((e) => e.id));
    const [checkpoint, setCheckpoint] = useState(character?.checkpoint || '');
    const [lora, setLora] = useState(character?.lora || '');
    const [basePrompt, setBasePrompt] = useState(
        character ? `portrait of ${character.name}, ${character.description || ''}` : ''
    );
    const [isSubmitting, setIsSubmitting] = useState(false);

    if (!isOpen || !character) return null;

    const toggleEmotion = (id) => {
        if (selectedEmotions.includes(id)) {
            setSelectedEmotions(selectedEmotions.filter((e) => e !== id));
        } else {
            setSelectedEmotions([...selectedEmotions, id]);
        }
    };

    const handleGenerate = async () => {
        if (selectedEmotions.length === 0) {
            toast.error('Select at least one emotion to generate');
            return;
        }

        setIsSubmitting(true);
        try {
            // api.post throws an ApiError carrying the server's `detail`,
            // which the catch below already toasts.
            const data = await api.post(
                `/api/v2/characters/${character.id}/expressions/generate`,
                {
                    emotions: selectedEmotions,
                    checkpoint: checkpoint || undefined,
                    lora: lora || undefined,
                    base_prompt: basePrompt || undefined,
                }
            );
            toast.success(
                `Enqueued ${data.job_ids?.length || selectedEmotions.length} expression generations!`,
                { icon: '✨' }
            );
            onClose();
        } catch (err) {
            toast.error(err.message || 'Generation failed');
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md animate-in fade-in duration-200">
            <div className="relative w-full max-w-xl bg-gray-900 border border-white/10 rounded-2xl shadow-2xl p-6 space-y-5 max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between border-b border-white/10 pb-4">
                    <h3 className="text-lg font-bold text-white flex items-center gap-2">
                        <Smile size={20} className="text-purple-400" />
                        <span>Expression Studio: {character.name}</span>
                    </h3>
                    <button
                        onClick={onClose}
                        className="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-white/10 transition-colors"
                        aria-label="Close modal"
                    >
                        <X size={20} />
                    </button>
                </div>

                <div className="space-y-4 text-xs">
                    <div className="space-y-1">
                        <label className="text-2xs font-bold text-purple-400 uppercase tracking-widest">
                            Base Character Prompt
                        </label>
                        <textarea
                            value={basePrompt}
                            onChange={(e) => setBasePrompt(e.target.value)}
                            rows={3}
                            className="w-full bg-black/40 border border-white/10 rounded-xl p-3 text-white placeholder-gray-500 outline-none focus:border-purple-500"
                            placeholder="Describe character appearance..."
                        />
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div className="space-y-1">
                            <label className="text-2xs font-bold text-gray-400 uppercase tracking-widest">
                                Checkpoint (Optional override)
                            </label>
                            <input
                                type="text"
                                value={checkpoint}
                                onChange={(e) => setCheckpoint(e.target.value)}
                                placeholder="Default checkpoint"
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-2.5 text-white placeholder-gray-600 outline-none focus:border-purple-500"
                            />
                        </div>
                        <div className="space-y-1">
                            <label className="text-2xs font-bold text-gray-400 uppercase tracking-widest">
                                Character LoRA (Optional)
                            </label>
                            <input
                                type="text"
                                value={lora}
                                onChange={(e) => setLora(e.target.value)}
                                placeholder="e.g. seraphina_v1.safetensors"
                                className="w-full bg-black/40 border border-white/10 rounded-xl p-2.5 text-white placeholder-gray-600 outline-none focus:border-purple-500"
                            />
                        </div>
                    </div>

                    <div className="space-y-2 pt-2">
                        <label className="text-2xs font-bold text-blue-400 uppercase tracking-widest">
                            Select Emotions to Generate ({selectedEmotions.length})
                        </label>
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                            {DEFAULT_EMOTIONS.map((emo) => {
                                const isSelected = selectedEmotions.includes(emo.id);
                                return (
                                    <button
                                        key={emo.id}
                                        type="button"
                                        onClick={() => toggleEmotion(emo.id)}
                                        className={`flex items-center justify-between p-2.5 rounded-xl border transition-all text-xs ${
                                            isSelected
                                                ? 'bg-purple-950/40 border-purple-600 text-purple-200 ring-1 ring-purple-500/30'
                                                : 'bg-black/20 border-white/5 text-gray-400 hover:bg-white/5'
                                        }`}
                                    >
                                        <span>{emo.label}</span>
                                        {isSelected && <span className="text-purple-400 font-bold">✓</span>}
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                </div>

                <div className="flex items-center justify-end gap-2 pt-4 border-t border-white/10">
                    <button
                        type="button"
                        onClick={onClose}
                        className="px-4 py-2 rounded-xl border border-white/10 bg-white/5 hover:bg-white/10 text-gray-300 transition-colors text-xs"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={handleGenerate}
                        disabled={isSubmitting || selectedEmotions.length === 0}
                        className="px-5 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-semibold transition-all text-xs flex items-center gap-2 shadow-lg shadow-purple-600/30 disabled:opacity-50"
                    >
                        {isSubmitting ? (
                            <>
                                <Loader2 size={14} className="animate-spin" />
                                <span>Queueing jobs...</span>
                            </>
                        ) : (
                            <>
                                <Sparkles size={14} />
                                <span>Generate {selectedEmotions.length} Expressions</span>
                            </>
                        )}
                    </button>
                </div>
            </div>
        </div>
    );
}
