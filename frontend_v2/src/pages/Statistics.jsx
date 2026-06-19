import { useQuery } from '@tanstack/react-query';
import { api } from '../api';
import {
    TrendingUp, Image, Clock, Sparkles, BarChart3,
    PieChart as PieChartIcon, Activity, Zap, Hash, MessageSquare, Loader2
} from 'lucide-react';
import {
    LineChart, Line, BarChart, Bar, PieChart, Pie,
    AreaChart, Area, Cell, XAxis, YAxis, CartesianGrid, Tooltip,
    ResponsiveContainer
} from 'recharts';

const COLORS = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#06b6d4', '#6366f1', '#ef4444'];

const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload && payload.length) {
        return (
            <div className="glass p-3 rounded-lg border border-gray-700/50">
                <p className="text-white font-medium">{label}</p>
                {payload.map((entry, index) => (
                    <p key={index} className="text-sm" style={{ color: entry.color }}>
                        {entry.name}: {entry.value}
                    </p>
                ))}
            </div>
        );
    }
    return null;
};

const Statistics = () => {

    // Fetch detailed statistics
    const { data, isLoading, error } = useQuery({
        queryKey: ['statistics', 'detailed'],
        queryFn: () => api.get('/api/statistics/detailed'),
        staleTime: 60000, // Cache for 1 minute
    });

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-screen bg-neutral-900">
                <Loader2 className="animate-spin text-blue-500" size={64} />
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="flex items-center justify-center h-screen bg-neutral-900">
                <div className="text-center">
                    <TrendingUp className="mx-auto mb-4 text-gray-600" size={64} />
                    <h2 className="text-2xl font-bold text-white mb-2">No Statistics Available</h2>
                    <p className="text-gray-400">
                        Generate images with enriched metadata to see comprehensive analytics
                    </p>
                </div>
            </div>
        );
    }

    // Prepare timeline data for charts
    const timelineDaily = Object.entries(data.timeline.daily).map(([date, count]) => ({
        date,
        count
    }));

    const timelineHourly = Object.entries(data.timeline.hourly).map(([hour, count]) => ({
        hour: `${hour}:00`,
        count
    }));

    // Prepare model data
    const checkpointsData = Object.entries(data.models.checkpoints).map(([name, count]) => ({
        name: name.length > 25 ? name.substring(0, 25) + '...' : name,
        fullName: name,
        count
    })).sort((a, b) => b.count - a.count).slice(0, 10);

    const samplersData = Object.entries(data.models.samplers).map(([name, count]) => ({
        name,
        count
    }));


    // Prepare settings data
    const stepsData = Object.entries(data.settings.steps).map(([steps, count]) => ({
        steps: parseInt(steps),
        count
    })).sort((a, b) => a.steps - b.steps);

    const cfgData = Object.entries(data.settings.cfg).map(([cfg, count]) => ({
        cfg: parseFloat(cfg),
        count
    })).sort((a, b) => a.cfg - b.cfg);

    const resolutionsData = Object.entries(data.settings.resolutions).map(([res, count]) => ({
        resolution: res,
        count
    })).sort((a, b) => b.count - a.count).slice(0, 8);

    // Prepare performance data
    const perfByModel = Object.entries(data.performance.by_model).map(([name, stats]) => ({
        name: name.length > 20 ? name.substring(0, 20) + '...' : name,
        avg: stats.avg
    })).sort((a, b) => b.avg - a.avg).slice(0, 8);

    const perfByRes = Object.entries(data.performance.by_resolution).map(([res, stats]) => ({
        resolution: res,
        avg: stats.avg
    })).sort((a, b) => a.avg - b.avg);

    return (
        <div className="min-h-screen bg-neutral-900 text-white p-6">
            <div className="max-w-7xl mx-auto space-y-6">
                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <h1 className="text-4xl font-bold mb-2 bg-gradient-to-r from-blue-500 to-purple-500 bg-clip-text text-transparent">
                            Generation Analytics
                        </h1>
                        <p className="text-gray-400">
                            Comprehensive insights from {data.total_images} generated images
                            {data.enriched_count > 0 && ` (${data.enriched_count} with full metadata)`}
                        </p>
                    </div>
                </div>

                {/* Overview Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="glass p-6 rounded-2xl">
                        <div className="flex items-center gap-3 mb-3">
                            <Image className="text-blue-500" size={24} />
                            <span className="text-sm text-gray-400">Total Images</span>
                        </div>
                        <div className="text-3xl font-bold">{data.total_images}</div>
                    </div>

                    <div className="glass p-6 rounded-2xl">
                        <div className="flex items-center gap-3 mb-3">
                            <Clock className="text-purple-500" size={24} />
                            <span className="text-sm text-gray-400">Avg Time</span>
                        </div>
                        <div className="text-3xl font-bold">{data.performance.avg_time || 0}s</div>
                    </div>

                    <div className="glass p-6 rounded-2xl">
                        <div className="flex items-center gap-3 mb-3">
                            <Sparkles className="text-pink-500" size={24} />
                            <span className="text-sm text-gray-400">Total Time</span>
                        </div>
                        <div className="text-3xl font-bold">
                            {Math.floor((data.performance.total_time || 0) / 60)}m
                        </div>
                    </div>

                    <div className="glass p-6 rounded-2xl">
                        <div className="flex items-center gap-3 mb-3">
                            <Hash className="text-green-500" size={24} />
                            <span className="text-sm text-gray-400">Keywords</span>
                        </div>
                        <div className="text-3xl font-bold">
                            {Object.keys(data.prompts.keywords || {}).length}
                        </div>
                    </div>
                </div>

                {/* Timeline Charts */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Daily Timeline */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <TrendingUp size={20} />
                            Daily Activity
                        </h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <AreaChart data={timelineDaily}>
                                <defs>
                                    <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.8} />
                                        <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis
                                    dataKey="date"
                                    stroke="#9ca3af"
                                    tick={{ fontSize: 12 }}
                                />
                                <YAxis stroke="#9ca3af" />
                                <Tooltip content={<CustomTooltip />} />
                                <Area
                                    type="monotone"
                                    dataKey="count"
                                    stroke="#3b82f6"
                                    fillOpacity={1}
                                    fill="url(#colorCount)"
                                />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Hourly Distribution */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <Activity size={20} />
                            Activity by Hour
                        </h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <BarChart data={timelineHourly}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis
                                    dataKey="hour"
                                    stroke="#9ca3af"
                                    tick={{ fontSize: 12 }}
                                />
                                <YAxis stroke="#9ca3af" />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="#8b5cf6" radius={[8, 8, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Model Analytics */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Top Checkpoints */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <BarChart3 size={20} />
                            Top Checkpoints
                        </h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <BarChart data={checkpointsData} layout="vertical">
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis type="number" stroke="#9ca3af" />
                                <YAxis
                                    dataKey="name"
                                    type="category"
                                    width={120}
                                    stroke="#9ca3af"
                                    tick={{ fontSize: 11 }}
                                />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="#3b82f6" radius={[0, 8, 8, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Sampler Distribution */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <PieChartIcon size={20} />
                            Sampler Distribution
                        </h3>
                        <ResponsiveContainer width="100%" height={300}>
                            <PieChart>
                                <Pie
                                    data={samplersData}
                                    cx="50%"
                                    cy="50%"
                                    labelLine={false}
                                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                                    outerRadius={100}
                                    fill="#8884d8"
                                    dataKey="count"
                                >
                                    {samplersData.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                                    ))}
                                </Pie>
                                <Tooltip content={<CustomTooltip />} />
                            </PieChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Settings Distribution */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Steps Distribution */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4">Steps Distribution</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <BarChart data={stepsData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis dataKey="steps" stroke="#9ca3af" />
                                <YAxis stroke="#9ca3af" />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="#10b981" radius={[8, 8, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>

                    {/* CFG Distribution */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4">CFG Distribution</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <BarChart data={cfgData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis dataKey="cfg" stroke="#9ca3af" />
                                <YAxis stroke="#9ca3af" />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="#f59e0b" radius={[8, 8, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Resolution Distribution */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4">Top Resolutions</h3>
                        <ResponsiveContainer width="100%" height={200}>
                            <BarChart data={resolutionsData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis
                                    dataKey="resolution"
                                    stroke="#9ca3af"
                                    tick={{ fontSize: 10 }}
                                    angle={-45}
                                    textAnchor="end"
                                    height={60}
                                />
                                <YAxis stroke="#9ca3af" />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="count" fill="#ec4899" radius={[8, 8, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Performance Metrics */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    {/* Performance by Model */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <Zap size={20} />
                            Average Time by Model
                        </h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <BarChart data={perfByModel} layout="vertical">
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis type="number" stroke="#9ca3af" />
                                <YAxis
                                    dataKey="name"
                                    type="category"
                                    width={100}
                                    stroke="#9ca3af"
                                    tick={{ fontSize: 11 }}
                                />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="avg" fill="#06b6d4" radius={[0, 8, 8, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Performance by Resolution */}
                    <div className="glass p-6 rounded-2xl">
                        <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                            <Activity size={20} />
                            Average Time by Resolution
                        </h3>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={perfByRes}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                                <XAxis
                                    dataKey="resolution"
                                    stroke="#9ca3af"
                                    tick={{ fontSize: 11 }}
                                    angle={-45}
                                    textAnchor="end"
                                    height={60}
                                />
                                <YAxis stroke="#9ca3af" />
                                <Tooltip content={<CustomTooltip />} />
                                <Line
                                    type="monotone"
                                    dataKey="avg"
                                    stroke="#8b5cf6"
                                    strokeWidth={3}
                                    dot={{ fill: '#8b5cf6', r: 5 }}
                                />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* Prompt Analytics */}
                <div className="glass p-6 rounded-2xl">
                    <h3 className="text-xl font-bold mb-4 flex items-center gap-2">
                        <MessageSquare size={20} />
                        Top Prompt Keywords
                    </h3>
                    <div className="flex flex-wrap gap-2">
                        {Object.entries(data.prompts.keywords || {}).slice(0, 50).map(([word, count]) => (
                            <div
                                key={word}
                                className="px-4 py-2 rounded-full glass border border-blue-500/30"
                                style={{
                                    fontSize: Math.max(12, Math.min(24, 12 + (count / 5)))
                                }}
                            >
                                <span className="text-white">{word}</span>
                                <span className="text-blue-400 ml-2 text-sm">({count})</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default Statistics;
