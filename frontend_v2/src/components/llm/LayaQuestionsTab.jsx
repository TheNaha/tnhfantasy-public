import React, { useState } from 'react';
import {
    HelpCircle, Plus, Edit2, Trash2, Check, RotateCcw,
    Shield, Sparkles, Filter, ChevronDown, ChevronUp, AlertCircle
} from 'lucide-react';
import clsx from 'clsx';
import toast from 'react-hot-toast';
import {
    usePipelineQuestions,
    useUpdateQuestionOverride,
    useCreateCustomQuestion,
    useDeleteQuestionOverride,
} from '../../hooks/usePipeline';

export default function LayaQuestionsTab() {
    const { data: questions = [], isLoading } = usePipelineQuestions();
    const updateMutation = useUpdateQuestionOverride();
    const createMutation = useCreateCustomQuestion();
    const deleteMutation = useDeleteQuestionOverride();

    const [stageFilter, setStageFilter] = useState('all');
    const [editingKey, setEditingKey] = useState(null);
    const [editText, setEditText] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);

    // New custom question form state
    const [newStage, setNewStage] = useState('triage');
    const [newKey, setNewKey] = useState('');
    const [newQuestion, setNewQuestion] = useState('');
    const [newDirective, setNewDirective] = useState('');
    const [newThreshold, setNewThreshold] = useState(0.60);

    const filteredQuestions = questions.filter(q => {
        if (stageFilter !== 'all' && q.stage !== stageFilter) return false;
        return true;
    });

    const handleToggleEnabled = async (q) => {
        try {
            await updateMutation.mutateAsync({
                stage: q.stage,
                key: q.key,
                updates: { enabled: !q.enabled },
            });
            toast.success(`${q.key} ${!q.enabled ? 'enabled' : 'disabled'}`);
        } catch {
            toast.error('Failed to update question toggle');
        }
    };

    const handleStartEdit = (q) => {
        setEditingKey(`${q.stage}:${q.key}`);
        setEditText(q.question);
    };

    const handleSaveEdit = async (q) => {
        try {
            await updateMutation.mutateAsync({
                stage: q.stage,
                key: q.key,
                updates: { question: editText },
            });
            setEditingKey(null);
            toast.success('Question text updated');
        } catch {
            toast.error('Failed to update question text');
        }
    };

    const handleResetQuestion = async (q) => {
        try {
            await deleteMutation.mutateAsync({ stage: q.stage, key: q.key });
            toast.success(q.is_custom ? 'Custom question deleted' : 'Question reset to default');
        } catch {
            toast.error('Failed to reset question');
        }
    };

    const handleCreateCustom = async (e) => {
        e.preventDefault();
        if (!newKey.trim() || !newQuestion.trim() || !newDirective.trim()) {
            toast.error('Please fill in key, question, and directive');
            return;
        }
        try {
            await createMutation.mutateAsync({
                stage: newStage,
                question: {
                    key: newKey.trim().toLowerCase().replace(/[^a-z0-9_]/g, '_'),
                    question: newQuestion.trim(),
                    directive: newDirective.trim(),
                    threshold: Number(newThreshold),
                },
            });
            setShowCreateModal(false);
            setNewKey('');
            setNewQuestion('');
            setNewDirective('');
            toast.success('Custom question authored!');
        } catch {
            toast.error('Failed to create custom question');
        }
    };

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 glass-panel p-6 rounded-2xl border border-white/10">
                <div>
                    <h3 className="text-xl font-bold text-white tracking-wide flex items-center gap-2">
                        <HelpCircle size={20} className="text-purple-400" />
                        Laya System 1 Questions &amp; Rubrics
                    </h3>
                    <p className="text-xs text-gray-400 mt-1">
                        Configure questions asked to Laya at each stage. Enable/disable checks, customize wording, or author custom directives.
                    </p>
                </div>

                <div className="flex items-center gap-2.5">
                    <div className="flex items-center bg-gray-900/80 border border-white/10 rounded-xl p-1">
                        {['all', 'triage', 'audit', 'chaining'].map((stg) => (
                            <button
                                key={stg}
                                type="button"
                                onClick={() => setStageFilter(stg)}
                                className={clsx(
                                    "px-3 py-1 rounded-lg text-xs font-semibold capitalize transition-all",
                                    stageFilter === stg
                                        ? "bg-purple-600 text-white shadow-md shadow-purple-600/30"
                                        : "text-gray-400 hover:text-white"
                                )}
                            >
                                {stg}
                            </button>
                        ))}
                    </div>

                    <button
                        type="button"
                        onClick={() => setShowCreateModal(true)}
                        className="px-3.5 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs flex items-center gap-1.5 shadow-md shadow-purple-600/20 transition-all shrink-0"
                    >
                        <Plus size={14} />
                        Add Question
                    </button>
                </div>
            </div>

            {/* Questions Grid */}
            {isLoading && questions.length === 0 ? (
                <div className="flex flex-col items-center justify-center p-12 text-center">
                    <div className="w-8 h-8 border-2 border-purple-500 border-t-transparent rounded-full animate-spin mb-3" />
                    <span className="text-xs text-gray-400 font-medium">Loading Laya questions…</span>
                </div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {filteredQuestions.map((q) => {
                    const editId = `${q.stage}:${q.key}`;
                    const isEditing = editingKey === editId;

                    return (
                        <div
                            key={editId}
                            className={clsx(
                                "p-5 rounded-2xl border transition-all duration-200 flex flex-col justify-between",
                                q.enabled
                                    ? "bg-gray-900/60 border-white/10 shadow-lg"
                                    : "bg-gray-950/40 border-white/5 opacity-60"
                            )}
                        >
                            <div>
                                <div className="flex items-center justify-between gap-2 mb-2.5">
                                    <div className="flex items-center gap-2">
                                        <span className={clsx(
                                            "px-2 py-0.5 rounded text-2xs font-bold uppercase tracking-wider border",
                                            q.stage === 'triage' ? "bg-blue-500/10 text-blue-400 border-blue-500/20" :
                                            q.stage === 'audit' ? "bg-amber-500/10 text-amber-400 border-amber-500/20" :
                                            "bg-cyan-500/10 text-cyan-400 border-cyan-500/20"
                                        )}>
                                            {q.stage}
                                        </span>
                                        <span className="text-2xs font-mono text-gray-400 font-semibold">{q.key}</span>
                                        {q.is_custom && (
                                            <span className="px-1.5 py-0.2 rounded bg-purple-500/20 text-purple-300 text-2xs font-bold">Custom</span>
                                        )}
                                        {q.is_gate && (
                                            <span className="px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 text-2xs font-bold">Gate</span>
                                        )}
                                    </div>

                                    {/* Enable/Disable Toggle */}
                                    <button
                                        type="button"
                                        onClick={() => handleToggleEnabled(q)}
                                        className={clsx(
                                            "w-9 h-5 rounded-full transition-colors relative p-0.5 shrink-0",
                                            q.enabled ? "bg-purple-600" : "bg-gray-800 border border-white/10"
                                        )}
                                        title={q.enabled ? "Disable question" : "Enable question"}
                                    >
                                        <div className={clsx(
                                            "w-4 h-4 rounded-full bg-white transition-transform shadow-sm",
                                            q.enabled ? "translate-x-4" : "translate-x-0"
                                        )} />
                                    </button>
                                </div>

                                {isEditing ? (
                                    <div className="space-y-2 mb-3">
                                        <textarea
                                            value={editText}
                                            onChange={(e) => setEditText(e.target.value)}
                                            rows={2}
                                            className="w-full p-2.5 rounded-xl bg-gray-950 border border-purple-500/50 text-xs text-white focus:outline-none"
                                        />
                                        <div className="flex items-center gap-2">
                                            <button
                                                type="button"
                                                onClick={() => handleSaveEdit(q)}
                                                className="px-3 py-1 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-bold text-2xs flex items-center gap-1"
                                            >
                                                <Check size={12} /> Save
                                            </button>
                                            <button
                                                type="button"
                                                onClick={() => setEditingKey(null)}
                                                className="px-3 py-1 rounded-lg bg-white/5 hover:bg-white/10 text-gray-300 text-2xs"
                                            >
                                                Cancel
                                            </button>
                                        </div>
                                    </div>
                                ) : (
                                    <p className="text-xs font-semibold text-gray-200 mb-2 leading-relaxed">
                                        {q.question}
                                    </p>
                                )}

                                {q.directive && (
                                    <div className="p-2 rounded-lg bg-purple-950/30 border border-purple-500/20 text-2xs text-purple-300 mb-2">
                                        <strong className="text-purple-200">Directive:</strong> {q.directive}
                                    </div>
                                )}

                                {q.options && Object.keys(q.options).length > 0 && (
                                    <div className="p-2 rounded-lg bg-black/20 border border-white/5 text-2xs text-gray-400 space-y-1 mb-2">
                                        <span className="font-bold text-gray-300 block">Options:</span>
                                        {Object.entries(q.options).map(([k, desc]) => (
                                            <div key={k} className="flex items-start gap-1">
                                                <code className="text-purple-300 shrink-0">{k}:</code>
                                                <span className="truncate">{desc}</span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            <div className="pt-2.5 border-t border-white/5 flex items-center justify-between text-2xs text-gray-500">
                                <span>Type: <strong className="text-gray-400 capitalize">{q.type}</strong></span>
                                <div className="flex items-center gap-2">
                                    {!isEditing && (
                                        <button
                                            type="button"
                                            onClick={() => handleStartEdit(q)}
                                            className="hover:text-purple-300 transition-colors flex items-center gap-0.5"
                                        >
                                            <Edit2 size={12} /> Edit
                                        </button>
                                    )}
                                    <button
                                        type="button"
                                        onClick={() => handleResetQuestion(q)}
                                        className="hover:text-red-400 transition-colors flex items-center gap-0.5"
                                        title={q.is_custom ? "Delete custom question" : "Reset to default"}
                                    >
                                        {q.is_custom ? <Trash2 size={12} /> : <RotateCcw size={12} />}
                                        {q.is_custom ? 'Delete' : 'Reset'}
                                    </button>
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
            )}

            {/* Author Custom Question Modal */}
            {showCreateModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-in fade-in duration-200">
                    <div className="w-full max-w-lg glass-panel p-6 rounded-2xl border border-white/10 bg-gray-900 shadow-2xl space-y-4">
                        <div className="flex items-center justify-between pb-3 border-b border-white/10">
                            <h4 className="text-sm font-bold text-white flex items-center gap-2">
                                <Plus size={16} className="text-purple-400" />
                                Author Custom Laya Question
                            </h4>
                            <button
                                type="button"
                                onClick={() => setShowCreateModal(false)}
                                className="text-gray-400 hover:text-white text-xs"
                            >
                                Close
                            </button>
                        </div>

                        <form onSubmit={handleCreateCustom} className="space-y-3.5">
                            <div>
                                <label className="text-2xs font-bold uppercase tracking-wider text-gray-400 block mb-1">
                                    Stage
                                </label>
                                <select
                                    value={newStage}
                                    onChange={(e) => setNewStage(e.target.value)}
                                    className="w-full px-3 py-2 rounded-xl bg-gray-950 border border-white/10 text-xs text-white focus:outline-none focus:border-purple-500/50"
                                >
                                    <option value="triage">Stage 1: Pre-Generation Triage</option>
                                    <option value="audit">Stage 2: Post-Generation Audit</option>
                                    <option value="chaining">Stage 3: Turn Chaining</option>
                                </select>
                            </div>

                            <div>
                                <label className="text-2xs font-bold uppercase tracking-wider text-gray-400 block mb-1">
                                    Question Key
                                </label>
                                <input
                                    type="text"
                                    value={newKey}
                                    onChange={(e) => setNewKey(e.target.value)}
                                    placeholder="e.g. check_whisper, tactical_opportunity"
                                    className="w-full px-3 py-2 rounded-xl bg-gray-950 border border-white/10 text-xs text-white focus:outline-none focus:border-purple-500/50 font-mono"
                                    required
                                />
                            </div>

                            <div>
                                <label className="text-2xs font-bold uppercase tracking-wider text-gray-400 block mb-1">
                                    Question Statement
                                </label>
                                <textarea
                                    value={newQuestion}
                                    onChange={(e) => setNewQuestion(e.target.value)}
                                    placeholder="e.g. Is the user whispering secret or forbidden knowledge?"
                                    rows={2}
                                    className="w-full px-3 py-2 rounded-xl bg-gray-950 border border-white/10 text-xs text-white focus:outline-none focus:border-purple-500/50"
                                    required
                                />
                            </div>

                            <div>
                                <label className="text-2xs font-bold uppercase tracking-wider text-gray-400 block mb-1">
                                    Directive (Injected when answer is YES)
                                </label>
                                <textarea
                                    value={newDirective}
                                    onChange={(e) => setNewDirective(e.target.value)}
                                    placeholder="e.g. Reply in hushed, guarded dialogue with paranoid body language."
                                    rows={2}
                                    className="w-full px-3 py-2 rounded-xl bg-gray-950 border border-white/10 text-xs text-white focus:outline-none focus:border-purple-500/50"
                                    required
                                />
                            </div>

                            <div>
                                <div className="flex justify-between items-center mb-1">
                                    <label className="text-2xs font-bold uppercase tracking-wider text-gray-400">
                                        Activation Probability Threshold
                                    </label>
                                    <span className="text-xs font-mono font-bold text-purple-400">{Math.round(newThreshold * 100)}%</span>
                                </div>
                                <input
                                    type="range"
                                    min="0.30"
                                    max="0.95"
                                    step="0.05"
                                    value={newThreshold}
                                    onChange={(e) => setNewThreshold(parseFloat(e.target.value))}
                                    className="w-full accent-purple-500"
                                />
                            </div>

                            <div className="pt-3 border-t border-white/10 flex justify-end gap-2">
                                <button
                                    type="button"
                                    onClick={() => setShowCreateModal(false)}
                                    className="px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 text-xs text-gray-300"
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-xs font-bold text-white shadow-lg shadow-purple-600/30"
                                >
                                    Create Question
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    );
}
