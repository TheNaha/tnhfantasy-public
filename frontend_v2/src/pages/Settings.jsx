import { useState } from 'react';
import { Settings as SettingsIcon, RotateCcw, Save, Info, Server } from 'lucide-react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { useConfirmation } from '../store/confirmationStore';
import { useSettings, useUpdateSettings } from '../store/settingsStore';
import { useBranding, useSaveBranding } from '../hooks/useBranding';


export default function Settings() {
    const settings = useSettings();
    const { updateSetting, resetCategory, resetSettings } = useUpdateSettings();
    const { confirm } = useConfirmation();

    const [activeTab, setActiveTab] = useState('ui');

    const handleUpdateSetting = (category, key, value) => {
        updateSetting(category, key, value);
        toast.success('Setting updated!');
    };

    const handleResetCategory = (category) => {
        resetCategory(category);
        toast.success(`${category.toUpperCase()} settings reset to defaults`, { icon: '↩️' });
    };

    const handleResetAll = async () => {
        const confirmed = await confirm({
            title: 'Reset All Settings',
            message: 'Are you sure you want to reset ALL settings to defaults? This cannot be undone.',
            confirmText: 'Reset All',
            isDangerous: true
        });
        if (confirmed) {
            resetSettings();
            toast.success('All settings reset to defaults', { icon: '↩️' });
        }
    };

    const handleTestToast = (type) => {
        const duration = type === 'success' ? settings.ui.toastSuccessDuration : settings.ui.toastErrorDuration;
        if (type === 'success') {
            toast.success(`Test toast (${duration}ms duration)`, { duration });
        } else {
            toast.error(`Test error toast (${duration}ms duration)`, { duration });
        }
    };

    const tabs = [
        { id: 'branding', label: 'Branding', icon: SettingsIcon },
        { id: 'ui', label: 'UI / UX', icon: SettingsIcon },
        { id: 'gallery', label: 'Gallery', icon: SettingsIcon },
        { id: 'models', label: 'Models', icon: SettingsIcon },
        { id: 'generator', label: 'Generator', icon: SettingsIcon },
    ];


    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="min-h-screen p-4 lg:p-8"
        >
            <div className="max-w-6xl mx-auto space-y-8">
                {/* Header */}
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 glass-panel p-6 rounded-3xl border border-white/5 shadow-2xl">
                    <div className="flex items-center gap-5">
                        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 border border-white/10 shadow-inner">
                            <SettingsIcon className="text-blue-400 drop-shadow-[0_0_10px_rgba(59,130,246,0.5)]" size={32} />
                        </div>
                        <div>
                            <h1 className="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 tracking-tight drop-shadow-md">
                                Settings
                            </h1>
                            <p className="text-gray-400 font-medium tracking-wide mt-1">Customize your ComfyUI experience</p>
                        </div>
                    </div>

                    <button
                        onClick={handleResetAll}
                        className="px-6 py-3 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 hover:border-red-500/40 rounded-xl text-red-400 hover:text-red-300 font-bold tracking-wide flex items-center gap-3 transition-all duration-300 shadow-inner group"
                    >
                        <RotateCcw size={20} className="group-hover:-rotate-180 transition-transform duration-500" />
                        Reset All
                    </button>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-12 gap-8">
                    {/* Sidebar Tabs */}
                    <div className="md:col-span-3 space-y-2 glass-panel p-4 rounded-3xl border border-white/5 shadow-2xl h-fit sticky top-8">
                        <div className="px-4 py-2 mb-2 text-[10px] font-bold uppercase tracking-widest text-gray-500">Categories</div>
                        {tabs.map(tab => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={`w-full flex items-center gap-4 px-5 py-4 rounded-2xl font-bold tracking-wide transition-all duration-300 shadow-inner ${activeTab === tab.id
                                    ? 'bg-gradient-to-r from-blue-600/20 to-violet-600/20 border border-blue-500/30 text-white shadow-[0_0_15px_rgba(59,130,246,0.1)]'
                                    : 'bg-white/5 border border-transparent text-gray-400 hover:bg-white/10 hover:text-white'
                                    }`}
                            >
                                <tab.icon size={20} className={activeTab === tab.id ? 'text-blue-400' : 'text-gray-500'} />
                                {tab.label}
                            </button>
                        ))}
                    </div>

                    {/* Content Area */}
                    <div className="md:col-span-9 glass-panel rounded-3xl border border-white/5 shadow-2xl p-8 min-h-[60vh]">
                        {activeTab === 'branding' && (<BrandingSettings />)}

                        {activeTab === 'ui' && (
                            <UISettings
                                settings={settings.ui}
                                onUpdate={(key, value) => handleUpdateSetting('ui', key, value)}
                                onReset={() => handleResetCategory('ui')}
                                onTestToast={handleTestToast}
                            />
                        )}

                        {activeTab === 'gallery' && (
                            <GallerySettings
                                settings={settings.gallery}
                                onUpdate={(key, value) => handleUpdateSetting('gallery', key, value)}
                                onReset={() => handleResetCategory('gallery')}
                            />
                        )}

                        {activeTab === 'models' && (
                            <ModelsSettings
                                settings={settings.models}
                                onUpdate={(key, value) => handleUpdateSetting('models', key, value)}
                                onReset={() => handleResetCategory('models')}
                            />
                        )}

                        {activeTab === 'generator' && (
                            <GeneratorSettings
                                settings={settings.generator}
                                onUpdate={(key, value) => handleUpdateSetting('generator', key, value)}
                                onReset={() => handleResetCategory('generator')}
                            />
                        )}
                    </div>
                </div>
            </div>
        </motion.div>
    );
}

// Branding Settings Component
function BrandingSettings() {
    const { data: branding, isLoading } = useBranding();
    const saveBranding = useSaveBranding();
    const [localBranding, setLocalBranding] = useState(null);

    const effectiveBranding = localBranding || branding;

    const handleSave = async () => {
        try {
            await saveBranding.mutateAsync(effectiveBranding);
            setLocalBranding(null);
            toast.success('Branding updated! Refresh the page to see changes.');
        } catch {
            toast.error('Failed to save branding settings');
        }
    };

    const handleReset = async () => {
        const defaultBranding = {
            appName: "TNH-Comfy",
            logoUrl: "/logo.png",
            faviconUrl: "/favicon.ico"
        };
        try {
            await saveBranding.mutateAsync(defaultBranding);
            setLocalBranding(null);
            toast.success('Branding reset to defaults. Refresh the page to see changes.');
        } catch {
            toast.error('Failed to reset branding settings');
        }
    };

    if (isLoading || !effectiveBranding) {
        return (
            <div className="flex flex-col items-center justify-center h-48 space-y-4">
                <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
                <div className="text-sm font-bold tracking-widest uppercase text-gray-500">Loading branding...</div>
            </div>
        );
    }

    return (
        <div className="space-y-8 animate-in fade-in duration-500">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-end gap-4 pb-6 border-b border-white/5">
                <div>
                    <h2 className="text-2xl font-bold tracking-wide text-white">Branding</h2>
                    <p className="text-sm font-medium text-gray-400 mt-2">
                        Customize your app's name and logo. Refresh the page after saving to see changes.
                    </p>
                </div>
                <div className="flex gap-3">
                    <button
                        onClick={handleReset}
                        className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner"
                    >
                        <RotateCcw size={16} /> Reset
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={isLoading}
                        className="px-6 py-2.5 bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 border border-white/10 rounded-xl text-white font-bold tracking-wide flex items-center gap-2 disabled:opacity-50 transition-all duration-300 shadow-lg hover:shadow-[0_0_15px_rgba(59,130,246,0.4)] transform active:scale-95"
                    >
                        <Save size={18} />
                        {isLoading ? 'Saving...' : 'Save'}
                    </button>
                </div>
            </div>

            <div className="grid gap-6">
                {/* App Name */}
                <SettingGroup title="App Name" description="The name displayed in the browser tab and sidebar">
                    <input
                        type="text"
                        value={effectiveBranding.appName}
                        onChange={(e) => setLocalBranding({ ...effectiveBranding, appName: e.target.value })}
                        className="w-full md:w-96 bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3.5 text-white font-medium focus:ring-2 focus:ring-blue-500/50 outline-none shadow-inner glow-focus transition-all"
                        placeholder="Enter app name"
                    />
                </SettingGroup>

                <div className="h-px w-full bg-gradient-to-r from-transparent via-white/5 to-transparent my-2" />

                {/* Logo Preview */}
                <SettingGroup title="App Logo" description="The logo image displayed in the sidebar">
                    <div className="flex items-center gap-6 glass-panel p-5 rounded-2xl border border-white/5 shadow-inner">
                        <div className="w-20 h-20 bg-[#0B0E14] rounded-xl border border-white/10 flex items-center justify-center p-3 shadow-inner relative group overflow-hidden">
                            <div className="absolute inset-0 bg-blue-500/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                            <img
                                src={effectiveBranding.logoUrl}
                                alt="Logo Preview"
                                className="w-full h-full object-contain drop-shadow-[0_0_10px_rgba(255,255,255,0.1)] relative z-10"
                                onError={(e) => {
                                    e.target.src = '/logo.png';
                                }}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <div className="flex items-center gap-2">
                                <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">Current</span>
                                <span className="text-sm font-medium text-gray-300 bg-white/5 px-2.5 py-1 rounded-lg border border-white/5">{effectiveBranding.logoUrl}</span>
                            </div>
                            <p className="text-xs text-gray-400 font-medium">To change: upload a new file to <code className="text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded border border-blue-500/20">/frontend/public/logo.png</code></p>
                        </div>
                    </div>
                </SettingGroup>

                {/* Favicon Info */}
                <SettingGroup title="Browser Favicon" description="The tiny icon displayed in your browser tab">
                    <div className="flex items-center gap-6 glass-panel p-5 rounded-2xl border border-white/5 shadow-inner">
                        <div className="w-12 h-12 bg-[#0B0E14] rounded-xl border border-white/10 flex items-center justify-center p-2 shadow-inner relative group overflow-hidden">
                            <div className="absolute inset-0 bg-purple-500/10 opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                            <img
                                src={effectiveBranding.faviconUrl}
                                alt="Favicon Preview"
                                className="w-full h-full object-contain relative z-10"
                                onError={(e) => {
                                    e.target.src = '/favicon.ico';
                                }}
                            />
                        </div>
                        <div className="space-y-1.5">
                            <div className="flex items-center gap-2">
                                <span className="text-[10px] font-bold uppercase tracking-widest text-gray-500">Current</span>
                                <span className="text-sm font-medium text-gray-300 bg-white/5 px-2.5 py-1 rounded-lg border border-white/5">{effectiveBranding.faviconUrl}</span>
                            </div>
                            <p className="text-xs text-gray-400 font-medium">To change: upload a new file to <code className="text-purple-400 bg-purple-500/10 px-1.5 py-0.5 rounded border border-purple-500/20">/frontend/public/favicon.ico</code></p>
                        </div>
                    </div>
                </SettingGroup>
            </div>

            <div className="bg-blue-500/10 border border-blue-500/30 rounded-2xl p-5 flex items-start gap-4 shadow-inner">
                <div className="bg-blue-500/20 p-2 rounded-xl flex-shrink-0">
                    <Info className="text-blue-400" size={20} />
                </div>
                <div>
                    <p className="font-bold tracking-wide text-blue-400 mb-1 text-sm uppercase">Note</p>
                    <p className="text-sm text-gray-300 font-medium leading-relaxed">
                        After saving your changes, you must <strong className="text-white">refresh the page</strong> (F5 or Cmd/Ctrl+R) to see the updated branding applied to the app interface.
                    </p>
                </div>
            </div>
        </div>
    );
}

// UI Settings Component
function UISettings({ settings, onUpdate, onReset, onTestToast }) {
    return (
        <div className="space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">UI / UX Settings</h2>
                <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                {/* Default View Mode */}
                <SettingGroup title="Default View Mode" description="Choose the default view mode for the gallery">
                    <select
                        value={settings.defaultViewMode}
                        onChange={(e) => onUpdate('defaultViewMode', e.target.value)}
                        className="w-full md:w-64 bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 text-white font-medium focus:ring-2 focus:ring-blue-500/50 shadow-inner glow-focus outline-none"
                    >
                        <option value="grid">Grid</option>
                        <option value="list">List</option>
                        <option value="feed">Feed</option>
                    </select>
                </SettingGroup>

                {/* Default Grid Columns */}
                <SettingGroup title="Default Grid Columns" description="Number of columns in grid view">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="2"
                            max="8"
                            value={settings.defaultGridColumns}
                            onChange={(e) => onUpdate('defaultGridColumns', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-lg w-8 text-center bg-white/5 py-1 rounded-lg border border-white/5">{settings.defaultGridColumns}</span>
                    </div>
                </SettingGroup>

                {/* Toast Duration */}
                <SettingGroup
                    title="Toast Success Duration"
                    description="How long success toasts stay visible (milliseconds)"
                    action={
                        <button
                            onClick={() => onTestToast('success')}
                            className="text-[11px] font-bold uppercase tracking-widest px-4 py-1.5 bg-green-500/10 hover:bg-green-500/20 border border-green-500/30 rounded-lg text-green-400 transition-colors shadow-inner"
                        >
                            Test
                        </button>
                    }
                >
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="1000"
                            max="10000"
                            step="500"
                            value={settings.toastSuccessDuration}
                            onChange={(e) => onUpdate('toastSuccessDuration', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-green-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.toastSuccessDuration}ms</span>
                    </div>
                </SettingGroup>

                <SettingGroup
                    title="Toast Error Duration"
                    description="How long error toasts stay visible (milliseconds)"
                    action={
                        <button
                            onClick={() => onTestToast('error')}
                            className="text-[11px] font-bold uppercase tracking-widest px-4 py-1.5 bg-red-500/10 hover:bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 transition-colors shadow-inner"
                        >
                            Test
                        </button>
                    }
                >
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="1000"
                            max="10000"
                            step="500"
                            value={settings.toastErrorDuration}
                            onChange={(e) => onUpdate('toastErrorDuration', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-red-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.toastErrorDuration}ms</span>
                    </div>
                </SettingGroup>

                {/* Animation Duration */}
                <SettingGroup title="Animation Duration" description="Speed of UI animations (milliseconds)">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="0"
                            max="500"
                            step="50"
                            value={settings.animationDuration}
                            onChange={(e) => onUpdate('animationDuration', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-purple-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.animationDuration}ms</span>
                    </div>
                </SettingGroup>

                {/* Query Cache Times */}
                <SettingGroup title="Data Stale Time" description="How long data is considered fresh before refetching (minutes)">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="1"
                            max="30"
                            value={settings.queryStaleTime / 60000}
                            onChange={(e) => onUpdate('queryStaleTime', parseInt(e.target.value) * 60000)}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.queryStaleTime / 60000} min</span>
                    </div>
                </SettingGroup>

                <SettingGroup title="Cache Time" description="How long data is kept in cache (minutes)">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="1"
                            max="60"
                            value={settings.queryCacheTime / 60000}
                            onChange={(e) => onUpdate('queryCacheTime', parseInt(e.target.value) * 60000)}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.queryCacheTime / 60000} min</span>
                    </div>
                </SettingGroup>
            </div>
        </div>
    );
}

// Gallery Settings Component
function GallerySettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">Gallery Settings</h2>
                <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                <SettingGroup title="Items Per Page" description="Number of items to load per page">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="10"
                            max="100"
                            step="10"
                            value={settings.itemsPerPage}
                            onChange={(e) => onUpdate('itemsPerPage', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-16 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.itemsPerPage}</span>
                    </div>
                </SettingGroup>

                <SettingGroup title="Auto-Refresh on Job Complete" description="Automatically refresh gallery when a generation completes">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.autoRefreshOnJobComplete}
                                onChange={(e) => onUpdate('autoRefreshOnJobComplete', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.autoRefreshOnJobComplete ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>

                <SettingGroup title="Silent Refresh" description="Refresh without showing loading indicators">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.silentRefresh}
                                onChange={(e) => onUpdate('silentRefresh', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.silentRefresh ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>
            </div>
        </div>
    );
}

// Models Settings Component
function ModelsSettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">Model Manager Settings</h2>
                <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                <SettingGroup title="Items Per Page" description="Number of models to display per page">
                    <div className="flex items-center gap-5">
                        <input
                            type="range"
                            min="10"
                            max="100"
                            step="10"
                            value={settings.itemsPerPage}
                            onChange={(e) => onUpdate('itemsPerPage', parseInt(e.target.value))}
                            className="w-full md:w-64 accent-blue-500"
                        />
                        <span className="text-white font-bold text-sm w-16 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.itemsPerPage}</span>
                    </div>
                </SettingGroup>

                <SettingGroup title="Auto-Remove Downloads" description="Automatically remove download status after completion">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.autoRemoveDownloads}
                                onChange={(e) => onUpdate('autoRemoveDownloads', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.autoRemoveDownloads ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>
            </div>
        </div>
    );
}

// Generator Settings Component
function GeneratorSettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-8 animate-in fade-in duration-500">
            <div className="flex justify-between items-end pb-6 border-b border-white/5">
                <h2 className="text-2xl font-bold tracking-wide text-white">Generator Settings</h2>
                <button onClick={onReset} className="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-gray-300 hover:text-white font-bold tracking-wide flex items-center gap-2 transition-all duration-300 shadow-inner">
                    <RotateCcw size={16} /> Reset
                </button>
            </div>

            <div className="grid gap-6">
                <SettingGroup title="Auto-Randomize Seed" description="Automatically randomize seed after each generation">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.autoRandomizeSeed}
                                onChange={(e) => onUpdate('autoRandomizeSeed', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.autoRandomizeSeed ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>

                <SettingGroup title="Redirect After Generate" description="Redirect to gallery after starting generation">
                    <label className="flex items-center gap-4 cursor-pointer group">
                        <div className="relative">
                            <input
                                type="checkbox"
                                checked={settings.redirectAfterGenerate}
                                onChange={(e) => onUpdate('redirectAfterGenerate', e.target.checked)}
                                className="sr-only peer"
                            />
                            <div className="w-11 h-6 bg-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
                        </div>
                        <span className="text-sm font-bold uppercase tracking-widest text-gray-400 group-hover:text-white transition-colors">{settings.redirectAfterGenerate ? 'Enabled' : 'Disabled'}</span>
                    </label>
                </SettingGroup>

                {settings.redirectAfterGenerate && (
                    <SettingGroup title="Redirect Delay" description="Delay before redirecting (milliseconds)">
                        <div className="flex items-center gap-5">
                            <input
                                type="range"
                                min="0"
                                max="5000"
                                step="500"
                                value={settings.redirectDelay}
                                onChange={(e) => onUpdate('redirectDelay', parseInt(e.target.value))}
                                className="w-full md:w-64 accent-blue-500"
                            />
                            <span className="text-white font-bold text-sm w-20 text-center bg-white/5 py-1.5 rounded-lg border border-white/5">{settings.redirectDelay}ms</span>
                        </div>
                    </SettingGroup>
                )}
            </div>
        </div>
    );
}

// Reusable Setting Group Component
function SettingGroup({ title, description, children, action }) {
    return (
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-6 pb-6 border-b border-white/5 last:border-0 last:pb-0">
            <div className="flex-1">
                <div className="flex items-center gap-3">
                    <h3 className="font-bold text-white tracking-wide">{title}</h3>
                    {action}
                </div>
                <p className="text-sm font-medium text-gray-400 mt-1">{description}</p>
            </div>
            <div className="shrink-0">
                {children}
            </div>
        </div>
    );
}
