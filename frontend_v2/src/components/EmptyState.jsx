import { ImageOff, Search, Package, FolderOpen, Star, Sparkles, Download } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';

// SVG Illustrations for each type
const EmptyIllustrations = {
    gallery: () => (
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="mx-auto mb-4">
            <motion.g
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.1 }}
            >
                {/* Image frame */}
                <rect x="20" y="25" width="80" height="60" rx="4" fill="url(#gradient1)" opacity="0.2" />
                <rect x="20" y="25" width="80" height="60" rx="4" stroke="currentColor" strokeWidth="2" className="text-gray-600" />
                {/* Mountain icon inside */}
                <path d="M35 65 L45 50 L55 60 L70 40 L85 65 Z" fill="currentColor" className="text-gray-700" opacity="0.3" />
                <circle cx="42" cy="40" r="4" fill="currentColor" className="text-gray-700" opacity="0.4" />
            </motion.g>
            <defs>
                <linearGradient id="gradient1" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#3b82f6" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.3" />
                </linearGradient>
            </defs>
        </svg>
    ),

    search: () => (
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="mx-auto mb-4">
            <motion.g
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.5 }}
            >
                {/* Magnifying glass */}
                <circle cx="50" cy="50" r="20" stroke="currentColor" strokeWidth="3" className="text-gray-600" />
                <line x1="65" y1="65" x2="80" y2="80" stroke="currentColor" strokeWidth="3" strokeLinecap="round" className="text-gray-600" />
                {/* X mark inside */}
                <line x1="45" y1="45" x2="55" y2="55" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-gray-500" />
                <line x1="55" y1="45" x2="45" y2="55" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-gray-500" />
            </motion.g>
        </svg>
    ),

    models: () => (
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="mx-auto mb-4">
            <motion.g
                initial={{ y: -10, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ duration: 0.5, type: "spring" }}
            >
                {/* Package box */}
                <path d="M60 30 L85 45 L85 75 L60 90 L35 75 L35 45 Z" stroke="currentColor" strokeWidth="2" className="text-gray-600" fill="url(#gradient2)" opacity="0.2" />
                <line x1="60" y1="30" x2="60" y2="90" stroke="currentColor" strokeWidth="2" className="text-gray-600" />
                <line x1="35" y1="45" x2="85" y2="45" stroke="currentColor" strokeWidth="2" className="text-gray-600" />
            </motion.g>
            <defs>
                <linearGradient id="gradient2" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#10b981" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.3" />
                </linearGradient>
            </defs>
        </svg>
    ),

    collection: () => (
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="mx-auto mb-4">
            <motion.g
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ duration: 0.5 }}
            >
                {/* Open folder */}
                <path d="M25 40 L25 80 C25 82 26 83 28 83 L92 83 C94 83 95 82 95 80 L95 50 C95 48 94 47 92 47 L55 47 L50 40 Z"
                    fill="url(#gradient3)" opacity="0.2" stroke="currentColor" strokeWidth="2" className="text-purple-500" />
                {/* Folder tab */}
                <path d="M25 40 L50 40 L55 47 L95 47" stroke="currentColor" strokeWidth="2" className="text-purple-500" />
            </motion.g>
            <defs>
                <linearGradient id="gradient3" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#8b5cf6" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#ec4899" stopOpacity="0.4" />
                </linearGradient>
            </defs>
        </svg>
    ),

    favorites: () => (
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="mx-auto mb-4">
            <motion.g
                initial={{ rotate: -10, opacity: 0 }}
                animate={{ rotate: 0, opacity: 1 }}
                transition={{ duration: 0.5, type: "spring" }}
            >
                {/* Star */}
                <path d="M60 30 L67 50 L90 50 L72 63 L78 85 L60 72 L42 85 L48 63 L30 50 L53 50 Z"
                    fill="url(#gradient4)" opacity="0.2" stroke="currentColor" strokeWidth="2" className="text-yellow-500" />
            </motion.g>
            <defs>
                <linearGradient id="gradient4" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#fbbf24" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.4" />
                </linearGradient>
            </defs>
        </svg>
    ),

    jobs: () => (
        <svg width="120" height="120" viewBox="0 0 120 120" fill="none" className="mx-auto mb-4">
            <motion.g
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.5 }}
            >
                {/* Clock/History icon */}
                <circle cx="60" cy="60" r="25" stroke="currentColor" strokeWidth="2" className="text-gray-600" fill="url(#gradient5)" opacity="0.1" />
                <motion.line
                    x1="60" y1="60" x2="60" y2="45"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-gray-600"
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{ duration: 0.5, delay: 0.2 }}
                />
                <motion.line
                    x1="60" y1="60" x2="72" y2="60"
                    stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="text-gray-600"
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{ duration: 0.5, delay: 0.4 }}
                />
            </motion.g>
            <defs>
                <linearGradient id="gradient5" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" stopColor="#6366f1" stopOpacity="0.3" />
                    <stop offset="100%" stopColor="#8b5cf6" stopOpacity="0.3" />
                </linearGradient>
            </defs>
        </svg>
    ),
};

const EmptyState = ({
    type = 'gallery',
    title,
    description,
    icon: CustomIcon,
    primaryAction,
    primaryLabel,
    secondaryAction,
    secondaryLabel,
    onAction,
    onSecondary,
    showTutorialHint = false
}) => {
    const navigate = useNavigate();

    // Enhanced config with better messaging
    const config = {
        gallery: {
            icon: ImageOff,
            title: title || "No images yet",
            description: description || "Start creating amazing AI-generated images with your prompts",
            primaryLabel: primaryLabel || "Generate Your First Image",
            primaryAction: primaryAction || (() => navigate('/generate')),
            secondaryLabel: secondaryLabel || "Browse Models",
            secondaryAction: secondaryAction || (() => navigate('/models')),
            tutorialHint: "💡 Tip: Start simple! Try prompts like 'a serene mountain landscape' or 'portrait of a cat'"
        },
        search: {
            icon: Search,
            title: title || "No results found",
            description: description || "We couldn't find any images matching your search. Try adjusting your filters or search terms.",
            primaryLabel: primaryLabel || "Clear Filters",
            primaryAction: primaryAction,
            secondaryLabel: null,
            tutorialHint: "💡 Tip: Use keywords from your prompts or try searching by model name"
        },
        models: {
            icon: Package,
            title: title || "No models found",
            description: description || "Download models from CivitAI to start generating images",
            primaryLabel: primaryLabel || "Browse CivitAI Models",
            primaryAction: primaryAction || (() => navigate('/models')),
            secondaryLabel: null,
            tutorialHint: "💡 Popular choices: SDXL models for quality, SD 1.5 for speed"
        },
        collection: {
            icon: FolderOpen,
            title: title || "Collection is empty",
            description: description || "Add images to this collection to organize your favorite generations",
            primaryLabel: primaryLabel || "Add Images",
            primaryAction: primaryAction,
            secondaryLabel: secondaryLabel || "View All Images",
            secondaryAction: secondaryAction || (() => navigate('/')),
            tutorialHint: "💡 Tip: Select images in the gallery and click 'Add to Collection'"
        },
        favorites: {
            icon: Star,
            title: title || "No favorites yet",
            description: description || "Star your best images to quickly find them later",
            primaryLabel: primaryLabel || "View All Images",
            primaryAction: primaryAction || (() => navigate('/')),
            secondaryLabel: null,
            tutorialHint: "💡 Tip: Click the star icon on any image to add it to favorites"
        },
        jobs: {
            icon: Sparkles,
            title: title || "No generations yet",
            description: description || "Your generation history will appear here once you start creating images",
            primaryLabel: primaryLabel || "Start Generating",
            primaryAction: primaryAction || (() => navigate('/generate')),
            secondaryLabel: secondaryLabel || "View Examples",
            tutorialHint: "💡 Tip: Each generation is saved with its prompt and settings for easy iteration"
        }
    };

    const currentConfig = config[type] || config.gallery;
    const Icon = CustomIcon || currentConfig.icon;
    const Illustration = EmptyIllustrations[type];

    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="flex flex-col items-center justify-center p-12 text-center max-w-md mx-auto"
        >
            {/* Illustration (if available) or Icon */}
            {Illustration ? (
                <Illustration />
            ) : (
                <motion.div
                    initial={{ scale: 0.8 }}
                    animate={{ scale: 1 }}
                    transition={{ duration: 0.3, type: "spring" }}
                    className="w-24 h-24 rounded-full bg-gray-800/50 flex items-center justify-center mb-6 border border-gray-700"
                >
                    <Icon size={40} className="text-gray-500" />
                </motion.div>
            )}

            {/* Title */}
            <h3 className="text-2xl font-bold text-white mb-3">
                {currentConfig.title}
            </h3>

            {/* Description */}
            <p className="text-gray-400 mb-6 leading-relaxed">
                {currentConfig.description}
            </p>

            {/* Tutorial Hint */}
            {showTutorialHint && currentConfig.tutorialHint && (
                <motion.div
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.3 }}
                    className="mb-6 px-4 py-3 bg-blue-500/10 border border-blue-500/30 rounded-lg text-sm text-blue-400"
                >
                    {currentConfig.tutorialHint}
                </motion.div>
            )}

            {/* Actions */}
            <div className="flex flex-col sm:flex-row gap-3 w-full">
                {currentConfig.primaryLabel && (
                    <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={onAction || currentConfig.primaryAction}
                        className="flex-1 px-6 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-blue-900/20 flex items-center justify-center gap-2"
                    >
                        <Sparkles size={18} />
                        {currentConfig.primaryLabel}
                    </motion.button>
                )}

                {currentConfig.secondaryLabel && (
                    <motion.button
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={onSecondary || currentConfig.secondaryAction}
                        className="flex-1 px-6 py-3 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-lg font-medium transition-all border border-gray-700"
                    >
                        {currentConfig.secondaryLabel}
                    </motion.button>
                )}
            </div>
        </motion.div>
    );
};

export default EmptyState;
