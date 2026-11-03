import { useState } from 'react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
    Sparkles, Server, Cpu, PartyPopper, Plus, ArrowRight, ArrowLeft, X, CheckCircle2,
    Wand2, ShieldCheck, LayoutTemplate,
} from 'lucide-react';
import useProvidersPageData from '../../hooks/useProvidersPageData';
import { useModelDirectories } from '../../hooks/useModelDirectories';
import { GENERATOR_MODEL_REQUESTS } from '../../constants/modelDirectories';
import { SETUP_COMPLETE_KEY, markSetupComplete } from '../../utils/setupComplete';
import { useEscapeKey } from '../../hooks/useEscapeKey';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import { api } from '../../api';

const STEPS = [
    { id: 'welcome', icon: Sparkles, title: 'Welcome to your Fantasy Engine' },
    { id: 'templates', icon: LayoutTemplate, title: 'Choose a world template' },
    { id: 'providers', icon: Server, title: 'Connect a provider' },
    { id: 'models', icon: Cpu, title: 'Install a checkpoint' },
    { id: 'ready', icon: PartyPopper, title: "You're ready" },
];

export default function OnboardingWizard({ onClose }) {
    useEscapeKey(onClose);
    const navigate = useNavigate();
    const [stepIndex, setStepIndex] = useState(0);
    const [selectedTemplateId, setSelectedTemplateId] = useState(null);
    const { providers, isLoading: providersLoading } = useProvidersPageData();
    const { modelsByKey, loading: modelsLoading } = useModelDirectories(GENERATOR_MODEL_REQUESTS);

    const { data: templatesData = { templates: [] }, isLoading: templatesLoading } = useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.TEMPLATES),
        queryFn: ({ signal }) => api.get('/api/v2/world-vault/onboarding/templates', { signal }),
    });
    const templates = templatesData.templates || [];

    const step = STEPS[stepIndex];
    const providerCount = providers?.length ?? 0;
    const checkpointCount = modelsByKey.checkpoints?.length ?? 0;

    const finish = () => {
        markSetupComplete();
        if (selectedTemplateId) {
            localStorage.setItem('tnh_selected_template', selectedTemplateId);
            toast.success(`Template '${templates.find(t => t.id === selectedTemplateId)?.name}' selected — apply it when creating your first world.`, { icon: '✨' });
        }
        toast.success('Setup complete — enjoy your Fantasy Engine!', { icon: '✨' });
        onClose();
    };

    const next = () => {
        if (stepIndex < STEPS.length - 1) setStepIndex(stepIndex + 1);
        else finish();
    };

    const canProceed = step.id === 'templates'
        ? selectedTemplateId !== null || templates.length === 0
        : true;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
            <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="w-full max-w-lg bg-gray-900 border border-white/10 rounded-3xl shadow-2xl max-h-[85vh] flex flex-col overflow-hidden"
            >
                <div className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-white/5 shrink-0">
                    <div className="flex items-center gap-2">
                        <step.icon size={18} className="text-blue-400" />
                        <span className="text-sm text-gray-400 font-medium">
                            Step {stepIndex + 1} of {STEPS.length}
                        </span>
                    </div>
                    <button
                        onClick={() => { markSetupComplete(); onClose(); }}
                        className="text-gray-500 hover:text-gray-300 transition-colors p-1"
                        aria-label="Dismiss onboarding"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div
                    className="flex gap-1.5 px-6 pt-3 shrink-0"
                    role="progressbar"
                    aria-valuenow={stepIndex + 1}
                    aria-valuemin={1}
                    aria-valuemax={STEPS.length}
                    aria-label="Onboarding progress"
                >
                    {STEPS.map((s, i) => (
                        <div
                            key={s.id}
                            className={`h-1 flex-1 rounded-full transition-colors ${i <= stepIndex ? 'bg-blue-500' : 'bg-gray-700'}`}
                        />
                    ))}
                </div>

                <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
                    <h2 className="text-2xl font-bold text-white mb-2">{step.title}</h2>

                    {step.id === 'welcome' && (
                        <div className="space-y-3 text-gray-400 text-sm leading-relaxed">
                            <p>
                                TNHFantasy is your private AI fantasy engine — unrestricted image
                                generation, immersive roleplay chatbots, and interactive story
                                crafting, all in one place.
                            </p>
                            <p>This 30-second tour will get your first image generating.</p>
                        </div>
                    )}

                    {step.id === 'templates' && (
                        <div className="space-y-4">
                            <p className="text-gray-400 text-sm leading-relaxed">
                                Start with a pre-built world or begin with a blank canvas. Templates
                                include characters, locations, lorebooks, scenarios, and a starter
                                story — all editable later.
                            </p>
                            {templatesLoading ? (
                                <div className="flex items-center gap-2 text-gray-400 text-sm">
                                    <div className="w-4 h-4 border-2 border-blue-500/30 border-t-transparent rounded-full animate-spin" />
                                    Loading templates…
                                </div>
                            ) : templates.length === 0 ? (
                                <div className="text-gray-500 text-sm">
                                    No templates available. Start with an empty world.
                                </div>
                            ) : (
                                <div className="grid grid-cols-1 gap-3">
                                    {templates.map((tmpl) => {
                                        const isSelected = selectedTemplateId === tmpl.id;
                                        return (
                                            <button
                                                key={tmpl.id}
                                                onClick={() => setSelectedTemplateId(isSelected ? null : tmpl.id)}
                                                className={`flex items-center gap-3 p-3 rounded-xl border transition-all ${isSelected
                                                    ? 'border-blue-500 bg-blue-500/10 text-white'
                                                    : 'border-white/10 bg-gray-800/50 hover:border-white/20 hover:bg-gray-800 text-gray-300'}`}
                                            >
                                                <div className="w-8 h-8 rounded-lg bg-gray-700 flex items-center justify-center shrink-0">
                                                    <Wand2 size={14} className={isSelected ? 'text-blue-400' : 'text-gray-500'} />
                                                </div>
                                                <div className="flex-1">
                                                    <div className="flex items-center justify-between">
                                                        <span className="text-sm font-semibold text-gray-200">{tmpl.name}</span>
                                                        {isSelected && <CheckCircle2 size={14} className="text-blue-400" />}
                                                    </div>
                                                    <p className="text-xs text-gray-500 mt-1">{tmpl.description}</p>
                                                    <span className="text-xs uppercase tracking-wider text-gray-500 mt-1 inline-block px-2 py-0.5 rounded bg-gray-700/50">
                                                        {tmpl.genre}
                                                    </span>
                                                </div>
                                            </button>
                                        );
                                    })}
                                    <button
                                        onClick={() => setSelectedTemplateId(null)}
                                        className={`flex items-center gap-3 p-3 rounded-xl border transition-all ${selectedTemplateId === null
                                            ? 'border-blue-500 bg-blue-500/10 text-white'
                                            : 'border-white/10 bg-gray-800/50 hover:border-white/20 hover:bg-gray-800 text-gray-300'}`}
                                    >
                                        <div className="w-8 h-8 rounded-lg bg-gray-700 flex items-center justify-center shrink-0">
                                            <ShieldCheck size={14} className={selectedTemplateId === null ? 'text-blue-400' : 'text-gray-500'} />
                                        </div>
                                        <div className="flex-1">
                                            <span className="text-sm font-semibold text-gray-200">Blank World</span>
                                            <p className="text-xs text-gray-500 mt-1">Start with an empty world — build everything from scratch</p>
                                        </div>
                                    </button>
                                </div>
                            )}
                            {selectedTemplateId && (
                                <div className="mt-3 p-3 rounded-lg bg-blue-500/10 border border-blue-500/20">
                                    <p className="text-sm text-blue-300">
                                        Selected: <span className="font-semibold">{templates.find(t => t.id === selectedTemplateId)?.name}</span>. You can always
                                        start over or build your own world later.
                                    </p>
                                </div>
                            )}
                        </div>
                    )}

                    {step.id === 'providers' && (
                        <div className="space-y-4">
                            <p className="text-gray-400 text-sm leading-relaxed">
                                Inference runs on serverless engines (Modal, Beam, hosted LLMs)
                                through the in-process provider engine. Add a provider manually
                                to get started.
                            </p>
                            <div className="rounded-2xl border border-white/10 bg-black/30 p-4 flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    {providerCount > 0 ? (
                                        <CheckCircle2 size={20} className="text-green-400" />
                                    ) : (
                                        <Server size={20} className="text-gray-500" />
                                    )}
                                    <div>
                                        <p className="text-sm font-bold text-white">
                                            {providersLoading ? 'Checking...' : `${providerCount} provider${providerCount === 1 ? '' : 's'} configured`}
                                        </p>
                                        <p className="text-xs text-gray-500">
                                            {providerCount > 0 ? 'Engines can receive jobs.' : 'None yet — add one below.'}
                                        </p>
                                    </div>
                                </div>
                                <button
                                    onClick={() => navigate('/providers')}
                                    className="flex items-center gap-2 text-blue-400 hover:text-blue-300 text-sm font-medium transition-colors"
                                >
                                    <Plus size={16} />
                                    Add a provider manually
                                </button>
                            </div>
                        </div>
                    )}

                    {step.id === 'models' && (
                        <div className="space-y-4">
                            <p className="text-gray-400 text-sm leading-relaxed">
                                Generation needs at least one checkpoint (a stable-diffusion
                                model) installed on a worker. Discovery lets you browse and
                                download thousands of models from CivitAI.
                            </p>
                            <div className="rounded-2xl border border-white/10 bg-black/30 p-4 flex items-center justify-between">
                                <div className="flex items-center gap-3">
                                    {checkpointCount > 0 ? (
                                        <CheckCircle2 size={20} className="text-green-400" />
                                    ) : (
                                        <Cpu size={20} className="text-gray-500" />
                                    )}
                                    <div>
                                        <p className="text-sm font-bold text-white">
                                            {modelsLoading ? 'Checking...' : `${checkpointCount} checkpoint${checkpointCount === 1 ? '' : 's'} installed`}
                                        </p>
                                        <p className="text-xs text-gray-500">
                                            {checkpointCount > 0 ? 'You can already generate.' : 'Browse the catalog to fix this.'}
                                        </p>
                                    </div>
                                </div>
                                <button
                                    onClick={() => navigate('/models/discover')}
                                    className="bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/30 text-amber-300 text-sm font-bold px-4 py-2 rounded-xl transition-all"
                                >
                                    Browse Discovery
                                </button>
                            </div>
                        </div>
                    )}

                    {step.id === 'ready' && (
                        <div className="space-y-3 text-gray-400 text-sm leading-relaxed">
                            <p>
                                Roleplay is your launchpad. Start a chat, write a story, or manage your
                                world vault at any time.
                            </p>
                            <p>
                                Tip: the seeded demo character <span className="text-white font-semibold">Lyra Vale</span> and
                                scenario are ready to play with in the vault.
                            </p>
                        </div>
                    )}
                </div>

                <div className="flex items-center justify-between px-6 py-4 border-t border-white/5 shrink-0">
                    <button
                        onClick={() => setStepIndex(Math.max(0, stepIndex - 1))}
                        disabled={stepIndex === 0}
                        className="flex items-center gap-2 text-gray-400 hover:text-gray-200 text-sm font-medium transition-colors disabled:opacity-30"
                    >
                        <ArrowLeft size={16} />
                        Back
                    </button>
                    <div className="flex items-center gap-3">
                        <button
                            onClick={() => { markSetupComplete(); onClose(); }}
                            className="text-gray-500 hover:text-gray-300 text-sm font-medium transition-colors"
                        >
                            Skip
                        </button>
                        <button
                            onClick={next}
                            disabled={!canProceed}
                            className={`flex items-center gap-2 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white text-sm font-bold px-5 py-2.5 rounded-xl transition-all transform active:scale-95 ${!canProceed ? 'opacity-50 cursor-not-allowed' : ''}`}
                        >
                            {stepIndex === STEPS.length - 1 ? 'Finish' : 'Continue'}
                            <ArrowRight size={16} />
                        </button>
                    </div>
                </div>
            </motion.div>
        </div>
    );
}
