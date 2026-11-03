import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
    BookOpen, Sparkles, ArrowRight, Loader2, FileText, LayoutList,
    Copy, Play, X,
} from 'lucide-react';
import { api } from '../api/client';
import toast from 'react-hot-toast';
import FormInput from '../components/common/FormInput';
import NumberInput from '../components/common/NumberInput';

/**
 * BatchStory — Generate multiple story chapter variants from one prompt.
 *
 * The user supplies a premise and a count N. The backend generates N distinct
 * chapter openings in one LLM job (batched prompts). The user reviews each
 * variant and picks one to continue as a story.
 */
export default function BatchStory() {
    const navigate = useNavigate();
    const [premise, setPremise] = useState('');
    const [count, setCount] = useState(3);

    const [results, setResults] = useState([]);
    const [selectedVariantId, setSelectedVariantId] = useState(null);

    const generateMutation = useMutation({
        mutationFn: async ({ premise, count }) => {
            const resp = await api.post('/api/v2/stories/batch-generate', {
                premise,
                count,
            });
            return resp.data;
        },
        onSuccess: (data) => {
            setResults(data.variants || []);
            toast.success(`Generated ${data.variants?.length || 0} chapter variants`, { id: 'batch-story' });
        },
        onError: (err) => {
            toast.error(`Failed to generate variants: ${err.message}`, { id: 'batch-story-error' });
        },
    });

    const handleGenerate = (e) => {
        e.preventDefault();
        if (!premise.trim()) {
            toast.error('Please enter a story premise');
            return;
        }
        generateMutation.mutate({ premise, count });
    };

    const handleSelect = (variantId) => {
        setSelectedVariantId(variantId);
    };

    const handleContinue = async () => {
        const variant = results.find((v) => v.id === selectedVariantId);
        if (!variant) return;
        try {
            const resp = await api.post('/api/v2/stories/from-variant', {
                variant_id: variant.id,
                title: variant.title || 'Untitled',
            });
            toast.success('Story created from variant', { id: 'batch-story-continue' });
            navigate(`/story/${resp.data.story_id}`);
        } catch (err) {
            toast.error(`Failed to create story: ${err.message}`, { id: 'batch-story-continue-error' });
        }
    };

    return (
        <div className="flex h-full flex-col bg-gray-900 text-white">
            <header className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-gray-800/50 shrink-0">
                <div className="flex items-center gap-2">
                    <BookOpen size={18} className="text-blue-400" />
                    <h1 className="text-lg font-semibold">Batch Story Variants</h1>
                </div>
                <p className="text-gray-400 text-sm">
                    Enter one premise and generate N distinct chapter openings.
                    Pick the best one to continue as a full story.
                </p>
            </header>

            <div className="flex-1 overflow-y-auto p-6 space-y-6">
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Input panel */}
                    <div className="lg:col-span-2 space-y-4">
                        <FormInput
                            label="Story Premise"
                            value={premise}
                            onChange={(e) => setPremise(e.target.value)}
                            rows={4}
                            placeholder="A knight discovers a dragon that doesn't want to fight…"
                        />
                        <div className="flex items-center gap-3">
                            <label className="text-sm text-gray-300">Number of variants</label>
                            <NumberInput
                                value={count}
                                onChange={(v) => setCount(Math.max(1, Math.min(10, parseInt(v) || 1)))}
                                min={1}
                                max={10}
                                step={1}
                                className="w-20"
                            />
                        </div>
                        <button
                            onClick={handleGenerate}
                            disabled={!premise.trim() || generateMutation.isPending}
                            className={`w-full flex items-center justify-center gap-2 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white font-bold px-6 py-3 rounded-xl transition-all transform active:scale-95 ${!premise.trim() || generateMutation.isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                            {generateMutation.isPending ? (
                                <>
                                    <Loader2 size={18} className="animate-spin" />
                                    Generating {count} variants…
                                </>
                            ) : (
                                <>
                                    <Sparkles size={18} />
                                    Generate Variants
                                </>
                            )}
                        </button>
                    </div>

                    {/* Controls */}
                    <div className="space-y-4">
                        <div className="rounded-lg border border-gray-700/50 bg-gray-800/30 p-4">
                            <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Tips</h3>
                            <ul className="text-sm text-gray-300 space-y-2 leading-relaxed">
                                <li className="flex items-start gap-2">
                                    <FileText size={14} className="text-blue-400 mt-0.5 shrink-0" />
                                    Be specific — include tone, setting, and conflict.
                                </li>
                                <li className="flex items-start gap-2">
                                    <LayoutList size={14} className="text-green-400 mt-0.5 shrink-0" />
                                    Each variant is a complete chapter opening.
                                </li>
                                <li className="flex items-start gap-2">
                                    <Copy size={14} className="text-purple-400 mt-0.5 shrink-0" />
                                    Pick one and continue writing in the editor.
                                </li>
                            </ul>
                        </div>
                    </div>
                </div>

                {/* Variants grid */}
                {results.length > 0 && (
                    <div className="border-t border-white/5 pt-6">
                        <div className="flex items-center justify-between mb-4">
                            <h2 className="text-lg font-semibold text-white">Generated Variants ({results.length})</h2>
                            <button
                                onClick={handleContinue}
                                disabled={!selectedVariantId || generateMutation.isPending}
                                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${selectedVariantId
                                    ? 'bg-green-600 hover:bg-green-500 text-white'
                                    : 'bg-gray-700 hover:bg-gray-600 text-gray-300 opacity-50 cursor-not-allowed'}`}
                            >
                                {selectedVariantId ? 'Continue with Selected' : 'Select a variant'}
                            </button>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                            {results.map((variant) => {
                                const isSelected = selectedVariantId === variant.id;
                                return (
                                    <div
                                        key={variant.id}
                                        className={`rounded-xl border p-4 transition-all ${isSelected
                                            ? 'border-blue-500 bg-blue-500/10 ring-1 ring-blue-500/20 shadow-[0_0_0_1px_rgba(59,130,246,0.2)]'
                                            : 'border-white/10 bg-gray-800/50 hover:border-gray-600/50'}`}
                                    >
                                        <div className="flex items-center justify-between mb-2">
                                            <span className="text-xs font-bold text-gray-300 uppercase tracking-wider">
                                                Variant {variant.index + 1}
                                            </span>
                                            <button
                                                onClick={() => handleSelect(variant.id)}
                                                className={`p-1 rounded text-gray-400 hover:text-white ${isSelected ? 'text-blue-400' : ''}`}
                                                aria-label={isSelected ? 'Deselect variant' : 'Select variant'}
                                            >
                                                                {isSelected ? <X size={16} /> : <Copy size={16} />}
                                                            </button>
                                        </div>
                                        <h3 className="text-sm font-semibold text-white mb-2">{variant.title || 'Untitled Variant'}</h3>
                                        <div className="text-sm text-gray-400 leading-relaxed mb-4 whitespace-pre-wrap break-words">
                                            {variant.content}
                                        </div>
                                        <div className="flex items-center justify-between text-xs text-gray-500">
                                            <span>{variant.word_count || 0} words</span>
                                            <span>{variant.chapter_number || 1}</span>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
