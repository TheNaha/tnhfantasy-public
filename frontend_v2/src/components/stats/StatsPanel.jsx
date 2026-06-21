import React, { useMemo, useEffect, useState } from 'react';
import { X, TrendingUp, Image as ImageIcon, CheckCircle, Clock, Sparkles, Loader2, BarChart2, Cpu, Layers } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import {
    BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Cell
} from 'recharts';

// Custom animated counter component
const AnimatedCounter = ({ value, duration = 1.5, suffix = '' }) => {
    const [count, setCount] = useState(0);

    useEffect(() => {
        let startTime;
        let animationFrame;
        const startValue = count;

        const animate = (timestamp) => {
            if (!startTime) startTime = timestamp;
            const progress = Math.min((timestamp - startTime) / (duration * 1000), 1);
            
            // Ease out expo
            const easeProgress = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
            
            setCount(startValue + (value - startValue) * easeProgress);

            if (progress < 1) {
                animationFrame = requestAnimationFrame(animate);
            }
        };

        animationFrame = requestAnimationFrame(animate);
        return () => cancelAnimationFrame(animationFrame);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [value, duration]);

    // Format based on whether it's an integer
    const displayValue = Number.isInteger(value) 
        ? Math.floor(count) 
        : count.toFixed(1);

    return <span>{displayValue}{suffix}</span>;
};

// Beautiful custom tooltip for Recharts
const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        return (
            <div className="bg-gray-900/90 backdrop-blur-md border border-white/10 p-3 rounded-xl shadow-2xl">
                <p className="text-white font-medium mb-1">{label}</p>
                <div className="flex items-center gap-2">
                    <div 
                        className="w-3 h-3 rounded-full shadow-[0_0_10px_rgba(255,255,255,0.5)]"
                        style={{ backgroundColor: payload[0].payload.color || '#3b82f6' }}
                    />
                    <p className="text-gray-300">
                        <span className="font-bold text-white">{payload[0].value}</span> uses
                    </p>
                </div>
            </div>
        );
    }
    return null;
};

const COLORS = [
    '#3b82f6', '#8b5cf6', '#ec4899', '#f43f5e', '#f59e0b', '#10b981', '#06b6d4', '#6366f1'
];

const StatsPanel = ({ isOpen, onClose }) => {
    const { data: stats, isLoading, error } = useQuery({
        queryKey: ['statistics'],
        queryFn: () => api.get('/api/statistics'),
        enabled: isOpen,
        staleTime: 30000,
    });

    const topModelsData = useMemo(() => {
        if (!stats?.models) return [];
        return Object.entries(stats.models)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([name, count], index) => ({
                name: name.replace('.safetensors', '').substring(0, 15) + (name.length > 15 ? '...' : ''),
                fullName: name,
                count,
                color: COLORS[index % COLORS.length]
            }));
    }, [stats]);

    const topLorasData = useMemo(() => {
        if (!stats?.loras) return [];
        return Object.entries(stats.loras)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([name, count], index) => ({
                name: name.replace('.safetensors', '').substring(0, 15) + (name.length > 15 ? '...' : ''),
                fullName: name,
                count,
                color: COLORS[(index + 3) % COLORS.length]
            }));
    }, [stats]);

    const containerVariants = {
        hidden: { opacity: 0, scale: 0.95, y: 20 },
        visible: { 
            opacity: 1, 
            scale: 1, 
            y: 0,
            transition: { 
                type: "spring", 
                damping: 25, 
                stiffness: 300,
                staggerChildren: 0.1,
                delayChildren: 0.1
            }
        },
        exit: { opacity: 0, scale: 0.95, y: 20, transition: { duration: 0.2 } }
    };

    const itemVariants = {
        hidden: { opacity: 0, y: 20 },
        visible: { opacity: 1, y: 0, transition: { type: "spring", damping: 20, stiffness: 200 } }
    };

    return (
        <AnimatePresence>
            {isOpen && (
                <div
                    className="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6"
                    onClick={onClose}
                >
                    {/* Ambient backdrop */}
                    <motion.div 
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="absolute inset-0 bg-black/60 backdrop-blur-xl"
                    />

                    {/* Glowing orbs in background */}
                    <motion.div 
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="absolute inset-0 overflow-hidden pointer-events-none"
                    >
                        <div className="absolute top-[20%] left-[30%] w-96 h-96 bg-blue-500/20 rounded-full blur-[120px] mix-blend-screen" />
                        <div className="absolute bottom-[20%] right-[30%] w-96 h-96 bg-purple-500/20 rounded-full blur-[120px] mix-blend-screen" />
                    </motion.div>

                    <motion.div
                        variants={containerVariants}
                        initial="hidden"
                        animate="visible"
                        exit="exit"
                        onClick={(e) => e.stopPropagation()}
                        className="relative w-full max-w-5xl max-h-[90vh] flex flex-col bg-gray-900/80 backdrop-blur-2xl border border-white/10 rounded-3xl shadow-[0_0_50px_rgba(0,0,0,0.5)] overflow-hidden"
                    >
                        {/* Shimmer effect border top */}
                        <div className="absolute top-0 inset-x-0 h-px bg-gradient-to-r from-transparent via-white/30 to-transparent" />

                        {/* Header */}
                        <div className="px-8 py-6 border-b border-white/5 flex items-center justify-between z-10 bg-gradient-to-b from-white/5 to-transparent">
                            <div className="flex items-center gap-4">
                                <div className="p-3 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl shadow-lg shadow-blue-500/20">
                                    <BarChart2 className="text-white" size={28} />
                                </div>
                                <div>
                                    <h2 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-gray-400 tracking-tight">
                                        Analytics Engine
                                    </h2>
                                    <p className="text-sm text-blue-200/60 font-medium tracking-wide uppercase mt-1">
                                        Generation Intelligence
                                    </p>
                                </div>
                            </div>
                            <button
                                onClick={onClose}
                                className="p-2.5 bg-white/5 hover:bg-white/10 rounded-xl text-gray-400 hover:text-white transition-all hover:scale-105 active:scale-95"
                            >
                                <X size={24} />
                            </button>
                        </div>

                        {/* Content */}
                        <div className="flex-1 overflow-y-auto p-8 custom-scrollbar">
                            {isLoading ? (
                                <div className="flex flex-col items-center justify-center h-64 gap-4">
                                    <div className="relative">
                                        <div className="absolute inset-0 bg-blue-500 blur-xl opacity-50 rounded-full animate-pulse" />
                                        <Loader2 className="animate-spin text-blue-400 relative z-10" size={56} />
                                    </div>
                                    <p className="text-gray-400 font-medium animate-pulse">Crunching numbers...</p>
                                </div>
                            ) : error || !stats || stats.total_images === 0 ? (
                                <motion.div variants={itemVariants} className="flex flex-col items-center justify-center h-80 text-center">
                                    <div className="w-24 h-24 mb-6 rounded-3xl bg-gradient-to-br from-gray-800 to-gray-900 border border-white/5 flex items-center justify-center shadow-xl">
                                        <Sparkles className="text-gray-500" size={40} />
                                    </div>
                                    <h3 className="text-2xl font-bold text-white mb-2">Awaiting Data</h3>
                                    <p className="text-gray-400 max-w-md">
                                        Your generation journey is just beginning. Create some masterpieces to unlock these insights.
                                    </p>
                                </motion.div>
                            ) : (
                                <div className="space-y-8">
                                    {/* Primary Metrics */}
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                                        {[
                                            { label: 'Total Images', value: stats.total_images || 0, icon: ImageIcon, color: 'from-blue-500 to-cyan-400', shadow: 'shadow-blue-500/20' },
                                            { label: 'Models Used', value: Object.keys(stats.models || {}).length, icon: Cpu, color: 'from-purple-500 to-pink-500', shadow: 'shadow-purple-500/20' },
                                            { label: 'LoRAs Explored', value: Object.keys(stats.loras || {}).length, icon: Layers, color: 'from-amber-400 to-orange-500', shadow: 'shadow-orange-500/20' },
                                            { label: 'Avg Speed', value: stats.avg_generation_time || 0, icon: Clock, color: 'from-emerald-400 to-teal-500', shadow: 'shadow-emerald-500/20', suffix: 's' }
                                        ].map((stat) => (
                                            <motion.div 
                                                key={stat.label}
                                                variants={itemVariants}
                                                className="relative overflow-hidden group rounded-3xl bg-white/5 border border-white/10 p-6 hover:bg-white/[0.07] transition-colors"
                                            >
                                                {/* Card glow effect */}
                                                <div className={`absolute -right-10 -top-10 w-32 h-32 bg-gradient-to-br ${stat.color} rounded-full blur-3xl opacity-20 group-hover:opacity-40 transition-opacity duration-500`} />
                                                
                                                <div className="flex justify-between items-start mb-4 relative z-10">
                                                    <div className={`p-2.5 rounded-xl bg-gradient-to-br ${stat.color} shadow-lg ${stat.shadow}`}>
                                                        <stat.icon className="text-white" size={20} />
                                                    </div>
                                                </div>
                                                
                                                <div className="relative z-10">
                                                    <h4 className="text-4xl font-black text-white mb-1 tracking-tight">
                                                        <AnimatedCounter value={stat.value} suffix={stat.suffix} />
                                                    </h4>
                                                    <p className="text-sm font-medium text-gray-400 tracking-wide uppercase">{stat.label}</p>
                                                </div>
                                            </motion.div>
                                        ))}
                                    </div>

                                    {/* Charts Section */}
                                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                                        {/* Top Models Chart */}
                                        {topModelsData.length > 0 && (
                                            <motion.div variants={itemVariants} className="bg-white/5 border border-white/10 rounded-3xl p-6 flex flex-col">
                                                <div className="flex items-center gap-3 mb-6">
                                                    <div className="p-2 bg-blue-500/20 rounded-lg">
                                                        <Cpu className="text-blue-400" size={20} />
                                                    </div>
                                                    <h3 className="text-xl font-bold text-white">Top Architecture</h3>
                                                </div>
                                                <div className="flex-1 min-h-[250px]">
                                                    <ResponsiveContainer width="100%" height="100%">
                                                        <BarChart data={topModelsData} layout="vertical" margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                                                            <XAxis type="number" hide />
                                                            <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ fill: '#9ca3af', fontSize: 12 }} width={120} />
                                                            <RechartsTooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} content={<CustomTooltip />} />
                                                            <Bar dataKey="count" radius={[0, 6, 6, 0]} barSize={24} animationDuration={1500}>
                                                                {topModelsData.map((entry, index) => (
                                                                    <Cell key={`cell-${index}`} fill={entry.color} />
                                                                ))}
                                                            </Bar>
                                                        </BarChart>
                                                    </ResponsiveContainer>
                                                </div>
                                            </motion.div>
                                        )}

                                        {/* Top LoRAs Chart */}
                                        {topLorasData.length > 0 && (
                                            <motion.div variants={itemVariants} className="bg-white/5 border border-white/10 rounded-3xl p-6 flex flex-col">
                                                <div className="flex items-center gap-3 mb-6">
                                                    <div className="p-2 bg-purple-500/20 rounded-lg">
                                                        <Layers className="text-purple-400" size={20} />
                                                    </div>
                                                    <h3 className="text-xl font-bold text-white">Top Enhancements</h3>
                                                </div>
                                                <div className="flex-1 min-h-[250px]">
                                                    <ResponsiveContainer width="100%" height="100%">
                                                        <BarChart data={topLorasData} layout="vertical" margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                                                            <XAxis type="number" hide />
                                                            <YAxis dataKey="name" type="category" axisLine={false} tickLine={false} tick={{ fill: '#9ca3af', fontSize: 12 }} width={120} />
                                                            <RechartsTooltip cursor={{ fill: 'rgba(255,255,255,0.05)' }} content={<CustomTooltip />} />
                                                            <Bar dataKey="count" radius={[0, 6, 6, 0]} barSize={24} animationDuration={1500}>
                                                                {topLorasData.map((entry, index) => (
                                                                    <Cell key={`cell-${index}`} fill={entry.color} />
                                                                ))}
                                                            </Bar>
                                                        </BarChart>
                                                    </ResponsiveContainer>
                                                </div>
                                            </motion.div>
                                        )}
                                    </div>

                                    {/* Parameters Grid */}
                                    <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                        {/* Steps */}
                                        {Object.keys(stats.popular_settings?.steps || {}).length > 0 && (
                                            <div className="bg-white/5 border border-white/10 rounded-2xl p-5 relative overflow-hidden">
                                                <div className="absolute top-0 right-0 w-32 h-32 bg-blue-500/10 blur-2xl rounded-full" />
                                                <h4 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">Sweet Spot: Steps</h4>
                                                <div className="space-y-3">
                                                    {Object.entries(stats.popular_settings.steps).slice(0, 3).map(([val, count], i) => (
                                                        <div key={val} className="flex items-center justify-between">
                                                            <div className="flex items-center gap-3">
                                                                <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${i === 0 ? 'bg-blue-500 text-white' : 'bg-gray-800 text-gray-400'}`}>
                                                                    {i + 1}
                                                                </span>
                                                                <span className="text-gray-200 font-medium">{val} steps</span>
                                                            </div>
                                                            <span className="text-gray-500 text-sm">{count}x</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* CFG */}
                                        {Object.keys(stats.popular_settings?.cfg || {}).length > 0 && (
                                            <div className="bg-white/5 border border-white/10 rounded-2xl p-5 relative overflow-hidden">
                                                <div className="absolute top-0 right-0 w-32 h-32 bg-purple-500/10 blur-2xl rounded-full" />
                                                <h4 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">Sweet Spot: CFG</h4>
                                                <div className="space-y-3">
                                                    {Object.entries(stats.popular_settings.cfg).slice(0, 3).map(([val, count], i) => (
                                                        <div key={val} className="flex items-center justify-between">
                                                            <div className="flex items-center gap-3">
                                                                <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${i === 0 ? 'bg-purple-500 text-white' : 'bg-gray-800 text-gray-400'}`}>
                                                                    {i + 1}
                                                                </span>
                                                                <span className="text-gray-200 font-medium">{val} CFG</span>
                                                            </div>
                                                            <span className="text-gray-500 text-sm">{count}x</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        {/* Resolution */}
                                        {Object.keys(stats.popular_settings?.resolution || {}).length > 0 && (
                                            <div className="bg-white/5 border border-white/10 rounded-2xl p-5 relative overflow-hidden">
                                                <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 blur-2xl rounded-full" />
                                                <h4 className="text-sm font-bold text-gray-400 uppercase tracking-wider mb-4">Sweet Spot: Resolution</h4>
                                                <div className="space-y-3">
                                                    {Object.entries(stats.popular_settings.resolution).slice(0, 3).map(([val, count], i) => (
                                                        <div key={val} className="flex items-center justify-between">
                                                            <div className="flex items-center gap-3">
                                                                <span className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${i === 0 ? 'bg-emerald-500 text-white' : 'bg-gray-800 text-gray-400'}`}>
                                                                    {i + 1}
                                                                </span>
                                                                <span className="text-gray-200 font-medium">{val}</span>
                                                            </div>
                                                            <span className="text-gray-500 text-sm">{count}x</span>
                                                        </div>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                    </motion.div>
                                </div>
                            )}
                        </div>
                    </motion.div>
                </div>
            )}
        </AnimatePresence>
    );
};

export default StatsPanel;
