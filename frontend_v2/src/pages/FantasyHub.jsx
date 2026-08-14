import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Wand2, MessageSquare, BookOpen, Image as ImageIcon, Sparkles, Gamepad2 } from 'lucide-react';
import clsx from 'clsx';

const CARDS = [
    {
        to: '/generate',
        icon: Wand2,
        title: 'Image Generation',
        description: 'Create stunning AI-generated images with simple prompts or advanced workflows. Supports img2img, inpainting, and ControlNet.',
        gradient: 'from-blue-500/20 to-cyan-500/20',
        iconColor: 'text-blue-400',
        borderColor: 'group-hover:border-blue-500/30',
    },
    {
        to: '/chat',
        icon: MessageSquare,
        title: 'Roleplay Chat',
        description: 'Engage in immersive character-driven conversations with AI personalities. Supports narration, scene generation, and agentic workflows.',
        gradient: 'from-purple-500/20 to-pink-500/20',
        iconColor: 'text-purple-400',
        borderColor: 'group-hover:border-purple-500/30',
    },
    {
        to: '/story',
        icon: BookOpen,
        title: 'Story Sandbox',
        description: 'Craft interactive stories with AI-assisted writing, chapter management, and integrated scene illustration. Your personal AI Dungeon.',
        gradient: 'from-amber-500/20 to-orange-500/20',
        iconColor: 'text-amber-400',
        borderColor: 'group-hover:border-amber-500/30',
    },
];

const container = {
    hidden: { opacity: 0 },
    show: {
        opacity: 1,
        transition: { staggerChildren: 0.1, delayChildren: 0.2 },
    },
};

const item = {
    hidden: { opacity: 0, y: 30 },
    show: { opacity: 1, y: 0, transition: { type: 'spring', stiffness: 300, damping: 24 } },
};

export default function FantasyHub() {
    const navigate = useNavigate();

    return (
        <div className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
            <motion.div
                className="text-center mb-12"
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6 }}
            >
                <div className="flex items-center justify-center gap-3 mb-4">
                    <Sparkles className="w-10 h-10 text-blue-400" />
                    <h1 className="text-4xl md:text-5xl font-bold text-gradient-primary tracking-tight">
                        Fantasy Hub
                    </h1>
                    <Sparkles className="w-10 h-10 text-purple-400" />
                </div>
                <p className="text-gray-400 text-lg max-w-2xl mx-auto">
                    Your comprehensive AI fantasy engine. Choose a workspace to begin creating.
                </p>
            </motion.div>

            <motion.div
                className="grid grid-cols-1 md:grid-cols-3 gap-6 w-full max-w-5xl"
                variants={container}
                initial="hidden"
                animate="show"
            >
                {CARDS.map(({ to, icon: Icon, title, description, gradient, iconColor, borderColor }) => (
                    <motion.div key={to} variants={item}>
                        <button
                            onClick={() => navigate(to)}
                            className={clsx(
                                "group w-full text-left rounded-2xl border border-white/10 bg-gradient-to-br p-8 transition-all duration-300 hover:scale-[1.02] hover:shadow-2xl focus-visible:ring-2 focus-visible:ring-blue-500 outline-none",
                                gradient,
                                borderColor
                            )}
                        >
                            <div className={clsx("w-14 h-14 rounded-xl flex items-center justify-center mb-6 bg-white/5 border border-white/10", iconColor)}>
                                <Icon size={28} />
                            </div>
                            <h2 className="text-2xl font-bold text-white mb-3 group-hover:text-blue-300 transition-colors">
                                {title}
                            </h2>
                            <p className="text-gray-400 text-sm leading-relaxed group-hover:text-gray-300 transition-colors">
                                {description}
                            </p>
                            <div className="mt-6 flex items-center gap-2 text-sm font-medium text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity">
                                <span>Enter workspace</span>
                                <span className="group-hover:translate-x-1 transition-transform">→</span>
                            </div>
                        </button>
                    </motion.div>
                ))}
            </motion.div>

            <motion.div
                className="mt-16 flex items-center gap-6 text-sm text-gray-500"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.8 }}
            >
                <div className="flex items-center gap-2">
                    <Gamepad2 size={16} />
                    <span>Three pillars of creation</span>
                </div>
                <div className="w-1 h-1 rounded-full bg-gray-600" />
                <div className="flex items-center gap-2">
                    <ImageIcon size={16} />
                    <span>Unified asset library</span>
                </div>
                <div className="w-1 h-1 rounded-full bg-gray-600" />
                <div className="flex items-center gap-2">
                    <Sparkles size={16} />
                    <span>Agentic AI workflows</span>
                </div>
            </motion.div>
        </div>
    );
}
