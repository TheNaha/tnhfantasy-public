import { BookOpen } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

/**
 * NoCheckpointCTA
 * Shown on generator pages when the worker has no checkpoints installed yet.
 * Fresh installs previously dead-ended silently: the checkpoint dropdown would
 * just read "No models found". This banner gives a direct path to discovery.
 */
export default function NoCheckpointCTA({ loading = false, show = true }) {
    const navigate = useNavigate();

    if (loading || !show) return null;

    return (
        <div className="mb-4 rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-500/10 to-orange-500/5 p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-amber-500/15 border border-amber-500/20 shrink-0">
                <BookOpen size={20} className="text-amber-400" />
            </div>
            <div className="min-w-0 flex-1">
                <p className="text-sm font-bold text-amber-300">No checkpoints installed yet</p>
                <p className="text-xs text-gray-400 mt-0.5">
                    Your workers have no stable-diffusion models on disk, so generation is disabled.
                    Discover and download a model to get started.
                </p>
            </div>
            <button
                onClick={() => navigate('/models/discover')}
                className="shrink-0 bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-black text-sm font-bold px-4 py-2 rounded-xl transition-all transform active:scale-95"
            >
                Find Models
            </button>
        </div>
    );
}