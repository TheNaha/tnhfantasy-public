import { useState, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import { motion } from 'framer-motion';
import {
    TrendingUp, Image, Clock, Sparkles, BarChart3,
    PieChart as PieChartIcon, Activity, Zap, Hash, MessageSquare, Loader2,
    Layers, Server, Calendar, Cpu, Leaf, Users
} from 'lucide-react';
import {
    LineChart, Line, BarChart, Bar, PieChart, Pie,
    Cell, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer
} from 'recharts';

const COLORS = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#06b6d4', '#6366f1', '#ef4444'];

const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        return (
            <motion.div 
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                className="bg-gray-950/90 p-3 rounded-xl border border-white/10 backdrop-blur-md shadow-2xl"
            >
                <p className="text-white font-medium mb-1">{label}</p>
                {payload.map((entry, index) => (
                    <p key={index} className="text-sm flex items-center gap-2" style={{ color: entry.color }}>
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }}/>
                        {entry.name}: <span className="font-bold text-white">{entry.value}</span>
                    </p>
                ))}
            </motion.div>
        );
    }
    return null;
};

// Heatmap Component
const ContributionHeatmap = ({ data }) => {
    const today = new Date();
    const days = [];
    for (let i = 364; i >= 0; i--) {
        const d = new Date(today.getFullYear(), today.getMonth(), today.getDate());
        d.setDate(d.getDate() - i);
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        days.push(`${year}-${month}-${day}`);
    }

    const dataMap = new Map(data.map(item => [item.date, item.count]));
    let maxCount = Math.max(...data.map(d => d.count), 1);

    const weeks = [];
    let currentWeek = [];
    
    const [y, m, d] = days[0].split('-');
    const firstDay = new Date(y, m - 1, d);
    for (let i = 0; i < firstDay.getDay(); i++) {
        currentWeek.push(null);
    }

    days.forEach(date => {
        currentWeek.push({
            date,
            count: dataMap.get(date) || 0
        });
        if (currentWeek.length === 7) {
            weeks.push(currentWeek);
            currentWeek = [];
        }
    });
    if (currentWeek.length > 0) {
        while (currentWeek.length < 7) currentWeek.push(null);
        weeks.push(currentWeek);
    }

    const getColor = (count) => {
        if (count === 0) return 'bg-neutral-800/50 border-neutral-700/30';
        const ratio = count / maxCount;
        if (ratio < 0.25) return 'bg-emerald-900/60 border-emerald-800/50';
        if (ratio < 0.5) return 'bg-emerald-700/80 border-emerald-600/50';
        if (ratio < 0.75) return 'bg-emerald-500 border-emerald-400/50';
        return 'bg-emerald-400 border-emerald-300 shadow-[0_0_10px_rgba(52,211,153,0.5)]';
    };

    const scrollContainerRef = useRef(null);

    useEffect(() => {
        if (scrollContainerRef.current) {
            scrollContainerRef.current.scrollLeft = scrollContainerRef.current.scrollWidth;
        }
    }, [weeks.length]);

    return (
        <div ref={scrollContainerRef} className="flex flex-col gap-2 overflow-x-auto pb-2 custom-scrollbar">
            <div className="flex gap-1.5" style={{ minWidth: 'max-content' }}>
                {weeks.map((week, i) => (
                    <motion.div 
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.005 }}
                        key={i} 
                        className="flex flex-col gap-1.5"
                    >
                        {week.map((day, j) => (
                            day ? (
                                <div
                                    key={day.date}
                                    title={`${day.count} images on ${day.date}`}
                                    className={`w-3 h-3 sm:w-3.5 sm:h-3.5 rounded-[3px] border ${getColor(day.count)} transition-all duration-300 hover:scale-125 hover:z-10 cursor-pointer`}
                                />
                            ) : (
                                <div key={`empty-${j}`} className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                            )
                        ))}
                    </motion.div>
                ))}
            </div>
            <div className="flex items-center justify-end gap-2 text-xs text-gray-400 mt-2 font-medium">
                <span>Less</span>
                <div className="flex gap-1">
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-neutral-800/50 border border-neutral-700/30" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-900/60 border border-emerald-800/50" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-700/80 border border-emerald-600/50" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-500 border border-emerald-400/50" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-400 border border-emerald-300 shadow-[0_0_5px_rgba(52,211,153,0.5)]" />
                </div>
                <span>More</span>
            </div>
        </div>
    );
};

// Container variants for staggered children animations
const containerVariants = {
    hidden: { opacity: 0 },
    show: {
        opacity: 1,
        transition: {
            staggerChildren: 0.1
        }
    }
};

const itemVariants = {
    hidden: { opacity: 0, y: 20 },
    show: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } }
};

const Statistics = () => {
    const [timeRange, setTimeRange] = useState('all');
    const [workspace, setWorkspace] = useState('all');

    const { data, isLoading, error, refetch } = useQuery({
        queryKey: ['statistics', 'detailed', timeRange],
        queryFn: () => api.get(`/api/statistics/detailed?timeRange=${timeRange}`),
        staleTime: 30000,
        refetchInterval: 120000,
    });

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-screen bg-neutral-950">
                <motion.div 
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="flex flex-col items-center gap-4"
                >
                    <Loader2 className="animate-spin text-blue-500" size={48} />
                    <p className="text-gray-400 font-medium">Analyzing Generation Telemetry...</p>
                </motion.div>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="flex items-center justify-center h-screen bg-neutral-950">
                <motion.div 
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="text-center bg-gray-900/50 backdrop-blur-xl p-8 rounded-3xl border border-white/10 max-w-md shadow-2xl"
                >
                    <TrendingUp className="mx-auto mb-4 text-gray-500" size={48} />
                    <h2 className="text-xl font-bold text-white mb-2">
                        {error ? 'Telemetry Offline' : 'No Data Available'}
                    </h2>
                    <p className="text-gray-400 mb-6 text-sm">
                        {error
                            ? 'The analytics service is currently unreachable.'
                            : 'Generate images to accumulate telemetry data.'}
                    </p>
                    {error && (
                        <button
                            onClick={() => refetch()}
                            className="px-5 py-2.5 bg-white text-black hover:bg-gray-200 font-medium rounded-xl transition-colors w-full"
                        >
                            Reconnect
                        </button>
                    )}
                </motion.div>
            </div>
        );
    }

    const timelineDaily = Object.entries(data?.timeline?.daily ?? {})
        .map(([date, count]) => ({ date, count }))
        .sort((a, b) => new Date(b.date) - new Date(a.date)); // Sort descending

    let currentStreak = 0;
    if (timelineDaily.length > 0) {
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        let checkDate = new Date(today);
        
        // Handle case where they haven't generated today yet but did yesterday
        const [fy, fm, fd] = timelineDaily[0].date.split('-');
        let firstDate = new Date(fy, fm - 1, fd);
        firstDate.setHours(0, 0, 0, 0);
        
        const diffDays = Math.floor((today.getTime() - firstDate.getTime()) / (1000 * 60 * 60 * 24));
        if (diffDays <= 1) {
            checkDate = firstDate; // Start checking from their most recent generation
            
            for (let i = 0; i < timelineDaily.length; i++) {
                const [ey, em, ed] = timelineDaily[i].date.split('-');
                const entryDate = new Date(ey, em - 1, ed);
                entryDate.setHours(0, 0, 0, 0);
                
                if (entryDate.getTime() === checkDate.getTime()) {
                    currentStreak++;
                    checkDate.setDate(checkDate.getDate() - 1); // Move back one day
                } else {
                    break;
                }
            }
        }
    }

    const timelineHourly = Object.entries(data?.timeline?.hourly ?? {}).map(([hour, count]) => ({
        hour: `${hour}:00`, count
    }));

    const checkpointsData = Object.entries(data?.models?.checkpoints ?? {}).map(([name, count]) => ({
        name: name.length > 25 ? name.substring(0, 25) + '...' : name,
        fullName: name,
        count
    })).sort((a, b) => b.count - a.count).slice(0, 10);

    const samplersData = Object.entries(data?.models?.samplers ?? {}).map(([name, count]) => ({
        name, count
    }));

    const stepsData = Object.entries(data?.settings?.steps ?? {}).map(([steps, count]) => ({
        steps: parseInt(steps), count
    })).sort((a, b) => a.steps - b.steps);

    const resolutionsData = Object.entries(data?.settings?.resolutions ?? {}).map(([res, count]) => ({
        resolution: res, count
    })).sort((a, b) => b.count - a.count).slice(0, 8);

    const TOTAL_HOURS = (data?.performance?.total_time || 0) / 3600;
    const KWH = TOTAL_HOURS * 0.35; 
    const CO2_EMISSIONS = KWH * 0.385; 

    const getTopCheckpointInsight = () => {
        if (!checkpointsData.length) return "Start generating to see your favorite styles!";
        const top = checkpointsData[0];
        const pct = ((top.count / Math.max(data.total_images, 1)) * 100).toFixed(1);
        return `You use ${top.fullName} ${pct}% of the time. You have found your aesthetic signature.`;
    };

    const getTopSamplerInsight = () => {
        if (!samplersData.length) return "No sampler data yet.";
        const top = [...samplersData].sort((a,b) => b.count - a.count)[0];
        const pct = ((top.count / Math.max(data.total_images, 1)) * 100).toFixed(1);
        if (top.name.toLowerCase().includes('euler')) return `Euler accounts for ${pct}% of your generations. Efficient and reliable.`;
        if (top.name.toLowerCase().includes('dpm')) return `DPM samplers make up ${pct}% of your runs. Quality over speed!`;
        return `Your go-to sampler is ${top.name} (${pct}%). A unique choice.`;
    };

    const ranges = [
        { value: '24h', label: '24H' },
        { value: '7d', label: '7D' },
        { value: '30d', label: '30D' },
        { value: 'all', label: 'ALL TIME' }
    ];

    return (
        <div className="min-h-screen relative p-4 md:p-8">
            <motion.div 
                key={timeRange}
                variants={containerVariants}
                initial="hidden"
                animate="show"
                className="max-w-7xl mx-auto space-y-4 md:space-y-8 relative z-10"
                style={{ opacity: 1 }}
            >
                <motion.div variants={itemVariants} className="flex flex-col md:flex-row md:items-end justify-between gap-6 glass-panel p-8 rounded-3xl border border-white/5 shadow-2xl">
                    <div>
                        <h1 className="text-2xl md:text-3xl font-black mb-2 tracking-tight bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent drop-shadow-md">
                            Telemetry & Insights
                        </h1>
                        <p className="text-gray-400 font-medium tracking-wide">
                            Synthesized from <span className="text-white font-bold px-2 py-0.5 bg-white/10 rounded-md border border-white/5">{data.total_images ?? 0}</span> generations
                        </p>
                    </div>
                    
                    <div className="flex flex-col sm:flex-row gap-3">
                        <div className="flex bg-[#0B0E14]/80 backdrop-blur-md border border-white/10 p-1.5 rounded-2xl w-fit shadow-inner">
                            {[
                                { value: 'all', label: 'ALL' },
                                { value: 'image', label: 'IMAGE' },
                                { value: 'chat', label: 'CHAT' },
                                { value: 'story', label: 'STORY' }
                            ].map((w) => (
                                <button
                                    key={w.value}
                                    onClick={() => setWorkspace(w.value)}
                                    className={`px-4 py-2 rounded-xl text-[11px] font-bold tracking-widest uppercase transition-all duration-300 ${workspace === w.value ? 'bg-white/10 text-white border border-white/20' : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'}`}
                                >
                                    {w.label}
                                </button>
                            ))}
                        </div>
                        <div className="flex bg-[#0B0E14]/80 backdrop-blur-md border border-white/10 p-1.5 rounded-2xl w-fit shadow-inner">
                        {ranges.map((r) => (
                            <button
                                key={r.value}
                                onClick={() => setTimeRange(r.value)}
                                className={`px-6 py-2 rounded-xl text-[11px] font-bold tracking-widest uppercase transition-all duration-300 ${timeRange === r.value ? 'bg-gradient-to-r from-blue-600/50 to-violet-600/50 text-white shadow-[0_0_15px_rgba(59,130,246,0.3)] border border-blue-500/50' : 'text-gray-400 hover:text-white hover:bg-white/5 border border-transparent'}`}
                            >
                                {r.label}
                            </button>
                        ))}
                    </div>
                </div>
                </motion.div>

                {(workspace === 'all' || workspace === 'image') && (<>
                <motion.div variants={itemVariants} className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <motion.div whileHover={{ scale: 1.02 }} className="group glass-panel p-4 md:p-6 rounded-3xl border border-white/5 flex flex-col sm:flex-row items-start sm:items-center gap-5 transition-all duration-500 hover:border-blue-500/40 hover:shadow-[0_0_30px_rgba(59,130,246,0.15)] relative overflow-hidden">
                        <div className="absolute inset-0 bg-gradient-to-br from-blue-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                        <div className="bg-blue-500/10 p-4 rounded-2xl text-blue-400 ring-1 ring-blue-500/30 group-hover:bg-blue-500/20 transition-colors shadow-inner relative z-10">
                            <Sparkles size={28} className="drop-shadow-[0_0_8px_rgba(59,130,246,0.5)]" />
                        </div>
                        <div className="relative z-10">
                            <h3 className="text-[10px] text-blue-400 font-bold tracking-widest uppercase mb-1">Aesthetic Signature</h3>
                            <p className="text-gray-300 text-sm font-medium leading-relaxed">{getTopCheckpointInsight()}</p>
                        </div>
                    </motion.div>
                    <motion.div whileHover={{ scale: 1.02 }} className="group glass-panel p-4 md:p-6 rounded-3xl border border-white/5 flex flex-col sm:flex-row items-start sm:items-center gap-5 transition-all duration-500 hover:border-purple-500/40 hover:shadow-[0_0_30px_rgba(168,85,247,0.15)] relative overflow-hidden">
                        <div className="absolute inset-0 bg-gradient-to-br from-purple-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
                        <div className="bg-purple-500/10 p-4 rounded-2xl text-purple-400 ring-1 ring-purple-500/30 group-hover:bg-purple-500/20 transition-colors shadow-inner relative z-10">
                            <Zap size={28} className="drop-shadow-[0_0_8px_rgba(168,85,247,0.5)]" />
                        </div>
                        <div className="relative z-10">
                            <h3 className="text-[10px] text-purple-400 font-bold tracking-widest uppercase mb-1">Workflow Preference</h3>
                            <p className="text-gray-300 text-sm font-medium leading-relaxed">{getTopSamplerInsight()}</p>
                        </div>
                    </motion.div>
                </motion.div>

                <motion.div variants={itemVariants} className="grid grid-cols-2 md:grid-cols-4 gap-6">
                    <motion.div whileHover={{ y: -5 }} className="glass-panel p-4 md:p-4 md:p-6 rounded-3xl border border-white/5 hover:border-white/10 hover:shadow-lg transition-all duration-300 relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                            <Image size={48} />
                        </div>
                        <div className="flex items-center gap-2 mb-4 text-gray-500 relative z-10">
                            <Image size={16} />
                            <span className="text-[10px] font-bold uppercase tracking-widest">Total Volume</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight text-white relative z-10 drop-shadow-md">{data.total_images ?? 0}</div>
                    </motion.div>

                    <motion.div whileHover={{ y: -5 }} className="glass-panel p-4 md:p-4 md:p-6 rounded-3xl border border-white/5 hover:border-white/10 hover:shadow-lg transition-all duration-300 relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                            <Clock size={48} />
                        </div>
                        <div className="flex items-center gap-2 mb-4 text-gray-500 relative z-10">
                            <Clock size={16} />
                            <span className="text-[10px] font-bold uppercase tracking-widest">Avg Speed</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight text-white relative z-10 drop-shadow-md">{data?.performance?.avg_time || 0}<span className="text-xl text-gray-500 ml-1">s</span></div>
                    </motion.div>

                    <motion.div whileHover={{ y: -5 }} className="glass-panel p-4 md:p-4 md:p-6 rounded-3xl border border-white/5 hover:border-white/10 hover:shadow-lg transition-all duration-300 relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-20 transition-opacity">
                            <Hash size={48} />
                        </div>
                        <div className="flex items-center gap-2 mb-4 text-gray-500 relative z-10">
                            <Hash size={16} />
                            <span className="text-[10px] font-bold uppercase tracking-widest">Unique Words</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight text-white relative z-10 drop-shadow-md">{Object.keys(data?.prompts?.keywords || {}).length}</div>
                    </motion.div>

                    <motion.div whileHover={{ y: -5 }} className="bg-gradient-to-br from-emerald-500/10 to-[#0B0E14]/80 backdrop-blur-md p-4 md:p-6 rounded-3xl border border-emerald-500/20 hover:border-emerald-500/40 hover:shadow-[0_0_20px_rgba(52,211,153,0.1)] transition-all duration-300 relative overflow-hidden group">
                        <div className="absolute top-0 right-0 p-4 opacity-10 text-emerald-400 group-hover:opacity-20 transition-opacity">
                            <Activity size={48} />
                        </div>
                        <div className="flex items-center gap-2 mb-4 text-emerald-500 relative z-10">
                            <Activity size={16} />
                            <span className="text-[10px] font-bold uppercase tracking-widest">Success Rate</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight text-emerald-400 relative z-10 drop-shadow-[0_0_15px_rgba(52,211,153,0.3)]">
                            {data?.performance?.success_rate != null
                                ? (data.performance.success_rate * 100).toFixed(0) + '%'
                                : '100%'}
                        </div>
                    </motion.div>
                </motion.div>

                <motion.div variants={itemVariants} className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 glass-panel p-8 rounded-3xl border border-white/5 hover:border-white/10 transition-all hover:shadow-xl flex flex-col">
                        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
                            <h3 className="text-lg font-black tracking-wide flex items-center gap-3 text-white">
                                <div className="p-2 bg-emerald-500/10 rounded-xl">
                                    <Calendar className="text-emerald-400 drop-shadow-[0_0_5px_rgba(52,211,153,0.5)]" size={20} />
                                </div>
                                Generation Streak
                            </h3>
                            <span className="text-[10px] font-bold tracking-widest bg-emerald-500/10 text-emerald-400 px-3 py-1.5 rounded-lg border border-emerald-500/20 shadow-inner uppercase">
                                {currentStreak} DAY STREAK
                            </span>
                        </div>
                        <div className="flex-1 flex flex-col justify-center">
                            <ContributionHeatmap data={timelineDaily} />
                        </div>
                    </div>

                    <div className="bg-gradient-to-br from-emerald-900/20 to-[#0B0E14]/80 backdrop-blur-md p-8 rounded-3xl border border-emerald-500/20 relative overflow-hidden group hover:border-emerald-500/40 transition-all hover:shadow-[0_0_30px_rgba(52,211,153,0.1)] flex flex-col">
                        <div className="absolute -right-10 -bottom-10 w-64 h-64 bg-emerald-500/10 rounded-full blur-[50px] pointer-events-none group-hover:bg-emerald-500/20 transition-colors duration-500" />
                        <h3 className="text-lg font-black tracking-wide mb-6 flex items-center gap-3 relative z-10 text-white">
                            <div className="p-2 bg-emerald-500/10 rounded-xl">
                                <Leaf className="text-emerald-400 drop-shadow-[0_0_5px_rgba(52,211,153,0.5)]" size={20} />
                            </div>
                            Resource Impact
                        </h3>
                        <div className="grid grid-cols-2 gap-4 relative z-10 flex-1 content-center">
                            <div className="col-span-2 bg-white/5 p-4 rounded-2xl border border-white/5 shadow-inner flex justify-between items-end">
                                <div>
                                    <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-1 flex items-center gap-2">
                                        <Cpu size={14} /> GPU Hours
                                    </div>
                                    <div className="text-2xl md:text-3xl font-black text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.3)]">
                                        {TOTAL_HOURS.toFixed(2)}<span className="text-lg text-emerald-600/50 ml-1 font-bold">h</span>
                                    </div>
                                </div>
                            </div>
                            
                            <div className="bg-white/5 p-4 rounded-2xl border border-white/5 shadow-inner flex flex-col justify-between">
                                <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-1">Power</div>
                                <div className="flex items-end gap-1">
                                    <div className="text-xl font-black text-white drop-shadow-sm">{KWH.toFixed(2)}</div>
                                    <span className="text-xs font-bold text-gray-500 mb-0.5">kWh</span>
                                </div>
                            </div>

                            <div className="bg-white/5 p-4 rounded-2xl border border-white/5 shadow-inner flex flex-col justify-between">
                                <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-1">Carbon</div>
                                <div className="flex items-end gap-1">
                                    <div className="text-xl font-black text-white drop-shadow-sm">{CO2_EMISSIONS.toFixed(2)}</div>
                                    <span className="text-xs font-bold text-gray-500 mb-0.5">kg</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </motion.div>

                <motion.div variants={itemVariants} className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="glass-panel p-8 rounded-3xl border border-white/5 hover:border-white/10 transition-all hover:shadow-xl">
                        <h3 className="text-lg font-black tracking-wide mb-8 flex items-center gap-3 text-white">
                            <div className="p-2 bg-blue-500/10 rounded-xl">
                                <BarChart3 className="text-blue-400 drop-shadow-[0_0_5px_rgba(59,130,246,0.5)]" size={20} />
                            </div>
                            Top Models
                        </h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={checkpointsData} layout="vertical" margin={{ left: 0, right: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff05" horizontal={true} vertical={false} />
                                <XAxis type="number" stroke="#ffffff20" tick={{fill: '#9ca3af', fontSize: 11, fontWeight: 'bold'}} axisLine={false} tickLine={false} />
                                <YAxis dataKey="name" type="category" width={150} stroke="#ffffff20" tick={{ fontSize: 11, fill: '#d1d5db', fontWeight: 'bold' }} axisLine={false} tickLine={false} />
                                <Tooltip cursor={{fill: '#ffffff05'}} content={<CustomTooltip />} />
                                <Bar dataKey="count" radius={[0, 6, 6, 0]} barSize={24}>
                                    {checkpointsData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={`url(#colorGradient${index % 2})`} />
                                    ))}
                                </Bar>
                                <defs>
                                    <linearGradient id="colorGradient0" x1="0" y1="0" x2="1" y2="0">
                                        <stop offset="0%" stopColor="#3b82f6" />
                                        <stop offset="100%" stopColor="#60a5fa" />
                                    </linearGradient>
                                    <linearGradient id="colorGradient1" x1="0" y1="0" x2="1" y2="0">
                                        <stop offset="0%" stopColor="#8b5cf6" />
                                        <stop offset="100%" stopColor="#a78bfa" />
                                    </linearGradient>
                                </defs>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="glass-panel p-8 rounded-3xl border border-white/5 hover:border-white/10 transition-all hover:shadow-xl">
                        <h3 className="text-lg font-black tracking-wide mb-8 flex items-center gap-3 text-white">
                            <div className="p-2 bg-purple-500/10 rounded-xl">
                                <Activity className="text-purple-400 drop-shadow-[0_0_5px_rgba(168,85,247,0.5)]" size={20} />
                            </div>
                            Hourly Activity
                        </h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={timelineHourly} margin={{ top: 10 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff05" vertical={false} />
                                <XAxis dataKey="hour" stroke="#ffffff20" tick={{ fontSize: 11, fill: '#9ca3af', fontWeight: 'bold' }} axisLine={false} tickLine={false} />
                                <YAxis stroke="#ffffff20" tick={{fill: '#9ca3af', fontSize: 11, fontWeight: 'bold'}} axisLine={false} tickLine={false} />
                                <Tooltip cursor={{fill: '#ffffff05'}} content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="url(#purpleGradient)" radius={[6, 6, 0, 0]} />
                                <defs>
                                    <linearGradient id="purpleGradient" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="0%" stopColor="#a855f7" />
                                        <stop offset="100%" stopColor="#7e22ce" />
                                    </linearGradient>
                                </defs>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </motion.div>

                <motion.div variants={itemVariants} className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="glass-panel p-8 rounded-3xl border border-white/5 hover:border-white/10 transition-all hover:shadow-xl">
                        <h3 className="text-[10px] font-bold tracking-widest uppercase mb-6 text-gray-500 flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-emerald-500" />
                            Steps Curve
                        </h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <LineChart data={stepsData} margin={{ top: 10 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff05" vertical={false} />
                                <XAxis dataKey="steps" stroke="#ffffff20" tick={{fontSize: 11, fill: '#9ca3af', fontWeight: 'bold'}} axisLine={false} tickLine={false} />
                                <YAxis stroke="#ffffff20" tick={{fontSize: 11, fill: '#9ca3af', fontWeight: 'bold'}} axisLine={false} tickLine={false} width={30} />
                                <Tooltip content={<CustomTooltip />} />
                                <Line type="monotone" dataKey="count" stroke="#10b981" strokeWidth={4} dot={{ fill: '#10b981', r: 4, strokeWidth: 0 }} activeDot={{ r: 6, stroke: '#047857', strokeWidth: 2 }} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="glass-panel p-8 rounded-3xl border border-white/5 hover:border-white/10 transition-all hover:shadow-xl">
                        <h3 className="text-[10px] font-bold tracking-widest uppercase mb-6 text-gray-500 flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-blue-500" />
                            Samplers
                        </h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <PieChart>
                                <Pie data={samplersData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} dataKey="count" stroke="none" paddingAngle={4}>
                                    {samplersData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip content={<CustomTooltip />} />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="glass-panel p-8 rounded-3xl border border-white/5 hover:border-white/10 transition-all hover:shadow-xl">
                        <h3 className="text-[10px] font-bold tracking-widest uppercase mb-6 text-gray-500 flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full bg-pink-500" />
                            Resolutions
                        </h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <BarChart data={resolutionsData} margin={{ top: 10, bottom: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff05" vertical={false} />
                                <XAxis dataKey="resolution" stroke="#ffffff20" tick={{ fontSize: 10, fill: '#9ca3af', fontWeight: 'bold' }} angle={-45} textAnchor="end" height={40} axisLine={false} tickLine={false} />
                                <YAxis stroke="#ffffff20" tick={{fontSize: 11, fill: '#9ca3af', fontWeight: 'bold'}} axisLine={false} tickLine={false} width={30} />
                                <Tooltip cursor={{fill: '#ffffff05'}} content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="url(#pinkGradient)" radius={[6, 6, 0, 0]} />
                                <defs>
                                    <linearGradient id="pinkGradient" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="0%" stopColor="#ec4899" />
                                        <stop offset="100%" stopColor="#be185d" />
                                    </linearGradient>
                                </defs>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </motion.div>

                <motion.div variants={itemVariants} className="bg-gradient-to-br from-[#0B0E14]/90 to-pink-900/20 backdrop-blur-xl p-10 rounded-[2.5rem] border border-pink-500/20 relative overflow-hidden group hover:border-pink-500/40 transition-all shadow-2xl">
                    <div className="absolute -right-20 -top-20 text-pink-500/5 rotate-12 pointer-events-none transition-transform duration-700 group-hover:rotate-[24deg] group-hover:scale-110">
                        <MessageSquare size={300} />
                    </div>
                    <h3 className="text-2xl font-black tracking-wide mb-8 flex items-center gap-3 relative z-10 text-white">
                        <div className="p-3 bg-pink-500/10 rounded-2xl">
                            <MessageSquare className="text-pink-400 drop-shadow-[0_0_8px_rgba(244,114,182,0.5)]" size={24} />
                        </div>
                        Prompt Anatomy
                    </h3>
                    <div className="flex flex-wrap items-center justify-center gap-3 relative z-10">
                        {Object.entries(data.prompts.keywords || {}).slice(0, 60).map(([word, count]) => {
                            const max = Object.values(data.prompts.keywords)[0] || 1;
                            const ratio = count / max;
                            return (
                                <motion.div
                                    key={word}
                                    whileHover={{ scale: 1.1, y: -2 }}
                                    className="px-5 py-2.5 rounded-2xl bg-white/5 backdrop-blur-md border border-white/5 hover:border-pink-400/50 hover:bg-pink-500/10 transition-all cursor-default shadow-inner"
                                    style={{
                                        fontSize: `${Math.max(0.85, Math.min(2.5, 0.85 + (ratio * 1.5)))}rem`,
                                        opacity: Math.max(0.6, Math.min(1, 0.6 + ratio)),
                                        fontWeight: ratio > 0.3 ? (ratio > 0.7 ? 900 : 700) : 500
                                    }}
                                >
                                    <span className="text-white tracking-wide">{word}</span>
                                </motion.div>
                            )
                        })}
                    </div>
                </motion.div>
                </>)}

                {(workspace === 'all' || workspace === 'chat' || workspace === 'story') && (
                <motion.div variants={itemVariants} className="glass-panel p-8 rounded-3xl border border-white/5 shadow-2xl">
                    <h3 className="text-lg font-black tracking-wide mb-6 flex items-center gap-3 text-white">
                        <div className="p-2 bg-violet-500/10 rounded-xl">
                            <Users className="text-violet-400" size={20} />
                        </div>
                        World Vault
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        {[
                            { label: 'Characters', value: data.pillars?.characters, color: 'text-violet-400' },
                            ...(workspace === 'chat' || workspace === 'all' ? [
                                { label: 'Chats', value: data.pillars?.chats, color: 'text-blue-400' },
                                { label: 'Messages', value: data.pillars?.messages, color: 'text-cyan-400' },
                                { label: 'LLM Jobs', value: data.pillars?.llm_jobs, color: 'text-teal-400' }
                            ] : []),
                            ...(workspace === 'story' || workspace === 'all' ? [
                                { label: 'Stories', value: data.pillars?.stories, color: 'text-emerald-400' },
                                { label: 'Chapters', value: data.pillars?.story_chapters, color: 'text-lime-400' },
                                { label: 'Lorebooks', value: data.pillars?.lorebooks, color: 'text-amber-400' }
                            ] : [])
                        ].map((p) => (
                            <div key={p.label} className="bg-white/5 p-4 rounded-2xl border border-white/5">
                                <div className="text-gray-500 text-[10px] font-bold uppercase tracking-widest mb-1">{p.label}</div>
                                <div className={`text-2xl font-black tracking-tight ${p.color}`}>{p.value ?? 0}</div>
                            </div>
                        ))}
                    </div>
                </motion.div>
                )}

            </motion.div>
        </div>
    );
};

export default Statistics;
