import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import {
    TrendingUp, Image, Clock, Sparkles, BarChart3,
    PieChart as PieChartIcon, Activity, Zap, Hash, MessageSquare, Loader2,
    Layers, Server, Calendar, Cpu, Leaf
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
            <div className="glass p-3 rounded-lg border border-gray-700/50 backdrop-blur-md">
                <p className="text-white font-medium mb-1">{label}</p>
                {payload.map((entry, index) => (
                    <p key={index} className="text-sm flex items-center gap-2" style={{ color: entry.color }}>
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }}/>
                        {entry.name}: <span className="font-bold text-white">{entry.value}</span>
                    </p>
                ))}
            </div>
        );
    }
    return null;
};

// Heatmap Component
const ContributionHeatmap = ({ data }) => {
    const today = new Date();
    const days = [];
    for (let i = 364; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        days.push(d.toISOString().split('T')[0]);
    }

    const dataMap = new Map(data.map(item => [item.date, item.count]));
    let maxCount = Math.max(...data.map(d => d.count), 1);

    const weeks = [];
    let currentWeek = [];
    
    const firstDay = new Date(days[0]);
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
        if (count === 0) return 'bg-neutral-800 border-neutral-700/50';
        const ratio = count / maxCount;
        if (ratio < 0.25) return 'bg-emerald-900/40 border-emerald-800/50';
        if (ratio < 0.5) return 'bg-emerald-700/60 border-emerald-600/50';
        if (ratio < 0.75) return 'bg-emerald-500 border-emerald-400/50';
        return 'bg-emerald-400 border-emerald-300';
    };

    return (
        <div className="flex flex-col gap-2 overflow-x-auto pb-2 custom-scrollbar">
            <div className="flex gap-1.5" style={{ minWidth: 'max-content' }}>
                {weeks.map((week, i) => (
                    <div key={i} className="flex flex-col gap-1.5">
                        {week.map((day, j) => (
                            day ? (
                                <div
                                    key={day.date}
                                    title={`${day.count} images on ${day.date}`}
                                    className={`w-3 h-3 sm:w-3.5 sm:h-3.5 rounded-[3px] border ${getColor(day.count)} transition-all hover:ring-2 hover:ring-white/50 cursor-pointer`}
                                />
                            ) : (
                                <div key={`empty-${j}`} className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
                            )
                        ))}
                    </div>
                ))}
            </div>
            <div className="flex items-center justify-end gap-2 text-xs text-gray-400 mt-2 font-medium">
                <span>Less</span>
                <div className="flex gap-1">
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-neutral-800 border border-neutral-700/50" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-900/40 border border-emerald-800/50" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-700/60 border border-emerald-600/50" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-500 border border-emerald-400/50" />
                    <div className="w-3.5 h-3.5 rounded-[3px] bg-emerald-400 border border-emerald-300" />
                </div>
                <span>More</span>
            </div>
        </div>
    );
};

const Statistics = () => {
    const [timeRange, setTimeRange] = useState('all');

    const { data, isLoading, error, refetch } = useQuery({
        queryKey: ['statistics', 'detailed', timeRange],
        queryFn: () => api.get('/api/statistics/detailed', { params: { timeRange } }),
        staleTime: 30000,
        refetchInterval: 120000,
    });

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-screen bg-neutral-950">
                <div className="flex flex-col items-center gap-4">
                    <Loader2 className="animate-spin text-blue-500" size={48} />
                    <p className="text-gray-400 font-medium">Analyzing Generation Telemetry...</p>
                </div>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="flex items-center justify-center h-screen bg-neutral-950">
                <div className="text-center glass p-8 rounded-2xl border border-neutral-800 max-w-md">
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
                            className="px-5 py-2.5 bg-white text-black hover:bg-gray-200 font-medium rounded-lg transition-colors w-full"
                        >
                            Reconnect
                        </button>
                    )}
                </div>
            </div>
        );
    }

    const timelineDaily = Object.entries(data?.timeline?.daily ?? {}).map(([date, count]) => ({
        date, count
    }));

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

    const cfgData = Object.entries(data?.settings?.cfg ?? {}).map(([cfg, count]) => ({
        cfg: parseFloat(cfg), count
    })).sort((a, b) => a.cfg - b.cfg);

    const resolutionsData = Object.entries(data?.settings?.resolutions ?? {}).map(([res, count]) => ({
        resolution: res, count
    })).sort((a, b) => b.count - a.count).slice(0, 8);

    const loraData = Object.entries(data?.models?.loras ?? {}).map(([name, count]) => ({
        name: name.length > 20 ? name.substring(0, 20) + '...' : name,
        count
    })).sort((a, b) => b.count - a.count).slice(0, 10);

    const providerData = Object.entries(data?.providers ?? {}).map(([name, count]) => ({
        name, count
    })).sort((a, b) => b.count - a.count);

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
        <div className="min-h-[calc(100vh-64px)] bg-neutral-950 text-white p-4 md:p-8 relative">
            <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-blue-900/10 rounded-full blur-[120px] pointer-events-none" />
            <div className="absolute bottom-0 left-0 w-[600px] h-[600px] bg-purple-900/10 rounded-full blur-[120px] pointer-events-none" />

            <div className="max-w-7xl mx-auto space-y-8 relative z-10">
                <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
                    <div>
                        <h1 className="text-4xl font-black mb-2 tracking-tight bg-gradient-to-r from-white to-gray-400 bg-clip-text text-transparent">
                            Telemetry & Insights
                        </h1>
                        <p className="text-gray-400 font-medium">
                            Synthesized from {data.total_images ?? 0} generations
                        </p>
                    </div>
                    
                    <div className="flex bg-neutral-900 border border-neutral-800 p-1.5 rounded-xl w-fit shadow-xl">
                        {ranges.map((r) => (
                            <button
                                key={r.value}
                                onClick={() => setTimeRange(r.value)}
                                className={`px-5 py-2 rounded-lg text-sm font-bold tracking-wide transition-all ${timeRange === r.value ? 'bg-white text-black shadow-sm' : 'text-gray-500 hover:text-white hover:bg-white/5'}`}
                            >
                                {r.label}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="glass p-6 rounded-2xl border-l-4 border-l-blue-500 flex flex-col sm:flex-row items-start sm:items-center gap-5 hover:bg-white/[0.02] transition-colors">
                        <div className="bg-blue-500/10 p-4 rounded-2xl text-blue-400 ring-1 ring-blue-500/20">
                            <Sparkles size={28} />
                        </div>
                        <div>
                            <h3 className="text-xs text-blue-400 font-black tracking-widest uppercase mb-2">Aesthetic Signature</h3>
                            <p className="text-gray-200 text-sm leading-relaxed">{getTopCheckpointInsight()}</p>
                        </div>
                    </div>
                    <div className="glass p-6 rounded-2xl border-l-4 border-l-purple-500 flex flex-col sm:flex-row items-start sm:items-center gap-5 hover:bg-white/[0.02] transition-colors">
                        <div className="bg-purple-500/10 p-4 rounded-2xl text-purple-400 ring-1 ring-purple-500/20">
                            <Zap size={28} />
                        </div>
                        <div>
                            <h3 className="text-xs text-purple-400 font-black tracking-widest uppercase mb-2">Workflow Preference</h3>
                            <p className="text-gray-200 text-sm leading-relaxed">{getTopSamplerInsight()}</p>
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="glass p-6 rounded-2xl border border-neutral-800/60 hover:border-neutral-700 transition-colors">
                        <div className="flex items-center gap-2 mb-4 text-gray-400">
                            <Image size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Total Volume</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight">{data.total_images ?? 0}</div>
                    </div>

                    <div className="glass p-6 rounded-2xl border border-neutral-800/60 hover:border-neutral-700 transition-colors">
                        <div className="flex items-center gap-2 mb-4 text-gray-400">
                            <Clock size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Avg Speed</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight">{data?.performance?.avg_time || 0}<span className="text-xl text-gray-600 ml-1">s</span></div>
                    </div>

                    <div className="glass p-6 rounded-2xl border border-neutral-800/60 hover:border-neutral-700 transition-colors">
                        <div className="flex items-center gap-2 mb-4 text-gray-400">
                            <Hash size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Unique Words</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight">{Object.keys(data?.prompts?.keywords || {}).length}</div>
                    </div>

                    <div className="glass p-6 rounded-2xl border border-neutral-800/60 hover:border-neutral-700 transition-colors relative overflow-hidden">
                        <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 rounded-full blur-[40px] pointer-events-none" />
                        <div className="flex items-center gap-2 mb-4 text-gray-400 relative z-10">
                            <Activity size={16} />
                            <span className="text-xs font-bold uppercase tracking-wider">Success Rate</span>
                        </div>
                        <div className="text-4xl font-black tracking-tight text-emerald-400 relative z-10">
                            {data?.performance?.success_rate != null
                                ? (data.performance.success_rate * 100).toFixed(0) + '%'
                                : '100%'}
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="lg:col-span-2 glass p-8 rounded-2xl border border-neutral-800/60">
                        <div className="flex justify-between items-center mb-8">
                            <h3 className="text-lg font-bold flex items-center gap-3">
                                <Calendar className="text-emerald-500" size={20} />
                                Generation Streak
                            </h3>
                            <span className="text-xs font-bold bg-emerald-500/10 text-emerald-400 px-3 py-1 rounded-full ring-1 ring-emerald-500/30">
                                {timelineDaily.length} ACTIVE DAYS
                            </span>
                        </div>
                        <ContributionHeatmap data={timelineDaily} />
                    </div>

                    <div className="glass p-8 rounded-2xl border border-emerald-900/30 bg-emerald-950/10 relative overflow-hidden">
                        <div className="absolute -right-10 -bottom-10 w-48 h-48 bg-emerald-500/10 rounded-full blur-[40px] pointer-events-none" />
                        <h3 className="text-lg font-bold mb-8 flex items-center gap-3 relative z-10">
                            <Leaf className="text-emerald-500" size={20} />
                            Resource Impact
                        </h3>
                        <div className="space-y-6 relative z-10">
                            <div>
                                <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2 flex items-center gap-2">
                                    <Cpu size={14} /> GPU Hours
                                </div>
                                <div className="text-3xl font-black text-emerald-400">
                                    {TOTAL_HOURS.toFixed(2)}<span className="text-lg text-emerald-600/50 ml-1">h</span>
                                </div>
                            </div>
                            
                            <div>
                                <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2">Power Usage</div>
                                <div className="text-xl font-bold">
                                    {KWH.toFixed(2)} <span className="text-sm text-gray-500">kWh</span>
                                </div>
                            </div>

                            <div>
                                <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-2">Est. Carbon</div>
                                <div className="text-xl font-bold">
                                    {CO2_EMISSIONS.toFixed(2)} <span className="text-sm text-gray-500">kg CO₂</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="glass p-8 rounded-2xl border border-neutral-800/60">
                        <h3 className="text-lg font-bold mb-8 flex items-center gap-3">
                            <BarChart3 className="text-blue-500" size={20} />
                            Top Models
                        </h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={checkpointsData} layout="vertical" margin={{ left: 0, right: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#262626" horizontal={true} vertical={false} />
                                <XAxis type="number" stroke="#525252" tick={{fill: '#737373', fontSize: 12}} axisLine={false} tickLine={false} />
                                <YAxis dataKey="name" type="category" width={150} stroke="#525252" tick={{ fontSize: 13, fill: '#a3a3a3', fontWeight: 500 }} axisLine={false} tickLine={false} />
                                <Tooltip cursor={{fill: '#262626'}} content={<CustomTooltip />} />
                                <Bar dataKey="count" radius={[0, 4, 4, 0]} barSize={24}>
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

                    <div className="glass p-8 rounded-2xl border border-neutral-800/60">
                        <h3 className="text-lg font-bold mb-8 flex items-center gap-3">
                            <Activity className="text-purple-500" size={20} />
                            Hourly Activity
                        </h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={timelineHourly} margin={{ top: 10 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
                                <XAxis dataKey="hour" stroke="#525252" tick={{ fontSize: 12, fill: '#737373' }} axisLine={false} tickLine={false} />
                                <YAxis stroke="#525252" tick={{fill: '#737373', fontSize: 12}} axisLine={false} tickLine={false} />
                                <Tooltip cursor={{fill: '#262626'}} content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="#a855f7" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    <div className="glass p-8 rounded-2xl border border-neutral-800/60">
                        <h3 className="text-sm font-bold tracking-widest uppercase mb-6 text-gray-400">Steps Curve</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <LineChart data={stepsData} margin={{ top: 10 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
                                <XAxis dataKey="steps" stroke="#525252" tick={{fontSize: 12, fill: '#737373'}} axisLine={false} tickLine={false} />
                                <YAxis stroke="#525252" tick={{fontSize: 12, fill: '#737373'}} axisLine={false} tickLine={false} width={30} />
                                <Tooltip content={<CustomTooltip />} />
                                <Line type="monotone" dataKey="count" stroke="#10b981" strokeWidth={4} dot={{ fill: '#10b981', r: 4, strokeWidth: 0 }} activeDot={{ r: 6 }} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="glass p-8 rounded-2xl border border-neutral-800/60">
                        <h3 className="text-sm font-bold tracking-widest uppercase mb-6 text-gray-400">Samplers</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <PieChart>
                                <Pie data={samplersData} cx="50%" cy="50%" innerRadius={60} outerRadius={80} dataKey="count" stroke="none" paddingAngle={2}>
                                    {samplersData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip content={<CustomTooltip />} />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>

                    <div className="glass p-8 rounded-2xl border border-neutral-800/60">
                        <h3 className="text-sm font-bold tracking-widest uppercase mb-6 text-gray-400">Resolutions</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <BarChart data={resolutionsData} margin={{ top: 10, bottom: 20 }}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#262626" vertical={false} />
                                <XAxis dataKey="resolution" stroke="#525252" tick={{ fontSize: 10, fill: '#737373' }} angle={-45} textAnchor="end" height={40} axisLine={false} tickLine={false} />
                                <YAxis stroke="#525252" tick={{fontSize: 12, fill: '#737373'}} axisLine={false} tickLine={false} width={30} />
                                <Tooltip cursor={{fill: '#262626'}} content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="#ec4899" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                <div className="glass p-10 rounded-3xl border border-pink-900/20 bg-gradient-to-br from-neutral-900/50 to-pink-900/5 relative overflow-hidden">
                    <div className="absolute -right-20 -top-20 text-pink-500/5 rotate-12 pointer-events-none">
                        <MessageSquare size={300} />
                    </div>
                    <h3 className="text-2xl font-bold mb-8 flex items-center gap-3 relative z-10">
                        <MessageSquare className="text-pink-500" size={24} />
                        Prompt Anatomy
                    </h3>
                    <div className="flex flex-wrap items-center justify-center gap-3 relative z-10">
                        {Object.entries(data.prompts.keywords || {}).slice(0, 60).map(([word, count]) => {
                            const max = Object.values(data.prompts.keywords)[0] || 1;
                            const ratio = count / max;
                            return (
                                <div
                                    key={word}
                                    className="px-4 py-2 rounded-xl bg-neutral-950/50 border border-neutral-800 hover:border-pink-500/50 hover:bg-pink-500/10 transition-all cursor-default shadow-sm"
                                    style={{
                                        fontSize: `${Math.max(0.85, Math.min(2.5, 0.85 + (ratio * 1.5)))}rem`,
                                        opacity: Math.max(0.6, Math.min(1, 0.6 + ratio)),
                                        fontWeight: ratio > 0.3 ? (ratio > 0.7 ? 800 : 600) : 400
                                    }}
                                >
                                    <span className="text-white">{word}</span>
                                </div>
                            )
                        })}
                    </div>
                </div>

            </div>
        </div>
    );
};

export default Statistics;
