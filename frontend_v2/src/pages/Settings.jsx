import { useState } from 'react';
import { Settings as SettingsIcon, RotateCcw, Save, Info, Server } from 'lucide-react';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { useConfirmation } from '../context/ConfirmationContext';
import { useSettings, useUpdateSettings } from '../store/settingsStore';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';


export default function Settings() {
    const _motion = motion;
    const settings = useSettings();
    const { updateSetting, resetCategory, resetSettings } = useUpdateSettings();
    const { confirm } = useConfirmation();

    const [activeTab, setActiveTab] = useState('ui');

    const handleUpdateSetting = (category, key, value) => {
        updateSetting(category, key, value);
        toast.success('Setting updated!', { duration: 1500 });
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
            className="min-h-screen bg-gray-900 text-white p-4 lg:p-8"
        >


            <div className="max-w-6xl mx-auto space-y-8">
                {/* Header */}
                <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                    <div className="min-w-0">
                        <h1 className="text-2xl sm:text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
                            Settings
                        </h1>
                        <p className="text-gray-400 mt-1 text-sm sm:text-base">Customize your ComfyUI experience</p>
                    </div>

                    <button
                        onClick={handleResetAll}
                        className="px-4 py-2 bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 rounded-lg text-red-400 flex items-center gap-2 transition-colors flex-shrink-0"
                    >
                        <RotateCcw size={18} />
                        Reset All
                    </button>
                </div>

                {/* Tabs */}
                <div className="flex gap-2 border-b border-gray-800 overflow-x-auto">
                    {tabs.map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`px-4 py-3 font-medium transition-colors border-b-2 whitespace-nowrap ${activeTab === tab.id
                                ? 'border-blue-500 text-white'
                                : 'border-transparent text-gray-400 hover:text-white'
                                }`}
                        >
                            {tab.label}
                        </button>
                    ))}
                </div>

                {/* Content */}
                <div className="bg-gray-800/50 rounded-xl border border-gray-700 p-6">
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
        </motion.div>
    );
}

// Branding Settings Component
function BrandingSettings() {
    const queryClient = useQueryClient();
    const [localBranding, setLocalBranding] = useState(null);

    // Fetch current branding
    const { data: branding, isLoading } = useQuery({
        queryKey: ['branding'],
        queryFn: () => api.get('/api/settings/branding'),
    });

    // Save branding mutation
    const saveMutation = useMutation({
        mutationFn: (data) => api.post('/api/settings/branding', data),
        onSuccess: () => {
            queryClient.invalidateQueries(['branding']);
            toast.success('Branding updated! Refresh the page to see changes.', { duration: 3000 });
        },
        onError: () => {
            toast.error('Failed to save branding settings');
        },
    });

    const effectiveBranding = localBranding || branding;

    const handleSave = () => {
        saveMutation.mutate(effectiveBranding);
    };

    const handleReset = () => {
        const defaultBranding = {
            appName: "TNH Comfy Gen",
            logoUrl: "/logo.png",
            faviconUrl: "/favicon.ico"
        };
        setLocalBranding(defaultBranding);
        saveMutation.mutate(defaultBranding);
    };

    if (isLoading || !effectiveBranding) {
        return <div className="text-gray-400">Loading branding settings...</div>;
    }

    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center mb-4">
                <div>
                    <h2 className="text-xl font-semibold">Branding Settings</h2>
                    <p className="text-sm text-gray-400 mt-1">
                        Customize your app's name and logo. Refresh the page after saving to see changes.
                    </p>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={handleReset}
                        className="text-sm text-gray-400 hover:text-white flex items-center gap-1 px-3 py-1 border border-gray-700 rounded-lg"
                    >
                        <RotateCcw size={14} /> Reset
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={saveMutation.isPending}
                        className="px-4 py-1 bg-blue-600 hover:bg-blue-500 text-white rounded-lg flex items-center gap-2 disabled:opacity-50"
                    >
                        <Save size={16} />
                        {saveMutation.isPending ? 'Saving...' : 'Save'}
                    </button>
                </div>
            </div>

            {/* App Name */}
            <SettingGroup title="App Name" description="The name displayed in the browser tab and sidebar">
                <input
                    type="text"
                    value={effectiveBranding.appName}
                    onChange={(e) => setLocalBranding({ ...effectiveBranding, appName: e.target.value })}
                    className="w-full md:w-80 bg-gray-900 border border-gray-700 rounded-lg p-2 text-white focus:border-blue-500 focus:outline-none"
                    placeholder="Enter app name"
                />
            </SettingGroup>

            {/* Logo Preview */}
            <SettingGroup title="Logo" description="The logo image displayed in the sidebar (current logo shown below)">
                <div className="flex items-center gap-4">
                    <div className="w-16 h-16 bg-gray-900 rounded-lg border border-gray-700 flex items-center justify-center p-2">
                        <img
                            src={effectiveBranding.logoUrl}
                            alt="Logo Preview"
                            className="w-full h-full object-contain"
                            onError={(e) => {
                                e.target.src = '/logo.png';
                            }}
                        />
                    </div>
                    <div className="text-sm text-gray-400">
                        <p>Current: {effectiveBranding.logoUrl}</p>
                        <p className="text-xs mt-1">To change: upload a new file to /frontend/public/logo.png</p>
                    </div>
                </div>
            </SettingGroup>

            {/* Favicon Info */}
            <SettingGroup title="Favicon" description="The icon displayed in the browser tab">
                <div className="flex items-center gap-4">
                    <div className="w-8 h-8 bg-gray-900 rounded border border-gray-700 flex items-center justify-center p-1">
                        <img
                            src={effectiveBranding.faviconUrl}
                            alt="Favicon Preview"
                            className="w-full h-full object-contain"
                            onError={(e) => {
                                e.target.src = '/favicon.ico';
                            }}
                        />
                    </div>
                    <div className="text-sm text-gray-400">
                        <p>Current: {effectiveBranding.faviconUrl}</p>
                        <p className="text-xs mt-1">To change: upload a new file to /frontend/public/favicon.ico</p>
                    </div>
                </div>
            </SettingGroup>

            <div className="bg-blue-900/20 border border-blue-500/30 rounded-lg p-4 flex items-start gap-3">
                <Info className="text-blue-400 flex-shrink-0 mt-0.5" size={20} />
                <div className="text-sm text-gray-300">
                    <p className="font-medium text-blue-400 mb-1">Note:</p>
                    <p>After saving your changes, <strong>refresh the page</strong> (F5 or Ctrl+R) to see the updated branding in the title and logo.</p>
                </div>
            </div>
        </div>
    );
}

// UI Settings Component
function UISettings({ settings, onUpdate, onReset, onTestToast }) {
    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-semibold">UI / UX Settings</h2>
                <button onClick={onReset} className="text-sm text-gray-400 hover:text-white flex items-center gap-1">
                    <RotateCcw size={14} /> Reset
                </button>
            </div>

            {/* Default View Mode */}
            <SettingGroup title="Default View Mode" description="Choose the default view mode for the gallery">
                <select
                    value={settings.defaultViewMode}
                    onChange={(e) => onUpdate('defaultViewMode', e.target.value)}
                    className="w-full md:w-64 bg-gray-900 border border-gray-700 rounded-lg p-2 text-white"
                >
                    <option value="grid">Grid</option>
                    <option value="list">List</option>
                    <option value="feed">Feed</option>
                </select>
            </SettingGroup>

            {/* Default Grid Columns */}
            <SettingGroup title="Default Grid Columns" description="Number of columns in grid view">
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="2"
                        max="8"
                        value={settings.defaultGridColumns}
                        onChange={(e) => onUpdate('defaultGridColumns', parseInt(e.target.value))}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-8">{settings.defaultGridColumns}</span>
                </div>
            </SettingGroup>

            {/* Toast Duration */}
            <SettingGroup
                title="Toast Success Duration"
                description="How long success toasts stay visible (milliseconds)"
                action={
                    <button
                        onClick={() => onTestToast('success')}
                        className="text-sm px-3 py-1 bg-green-600/20 hover:bg-green-600/30 border border-green-500/30 rounded text-green-400"
                    >
                        Test
                    </button>
                }
            >
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="1000"
                        max="10000"
                        step="500"
                        value={settings.toastSuccessDuration}
                        onChange={(e) => onUpdate('toastSuccessDuration', parseInt(e.target.value))}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-20">{settings.toastSuccessDuration}ms</span>
                </div>
            </SettingGroup>

            <SettingGroup
                title="Toast Error Duration"
                description="How long error toasts stay visible (milliseconds)"
                action={
                    <button
                        onClick={() => onTestToast('error')}
                        className="text-sm px-3 py-1 bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 rounded text-red-400"
                    >
                        Test
                    </button>
                }
            >
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="1000"
                        max="10000"
                        step="500"
                        value={settings.toastErrorDuration}
                        onChange={(e) => onUpdate('toastErrorDuration', parseInt(e.target.value))}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-20">{settings.toastErrorDuration}ms</span>
                </div>
            </SettingGroup>

            {/* Animation Duration */}
            <SettingGroup title="Animation Duration" description="Speed of UI animations (milliseconds)">
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="0"
                        max="500"
                        step="50"
                        value={settings.animationDuration}
                        onChange={(e) => onUpdate('animationDuration', parseInt(e.target.value))}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-20">{settings.animationDuration}ms</span>
                </div>
            </SettingGroup>

            {/* Query Cache Times */}
            <SettingGroup title="Data Stale Time" description="How long data is considered fresh before refetching (minutes)">
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="1"
                        max="30"
                        value={settings.queryStaleTime / 60000}
                        onChange={(e) => onUpdate('queryStaleTime', parseInt(e.target.value) * 60000)}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-20">{settings.queryStaleTime / 60000} min</span>
                </div>
            </SettingGroup>

            <SettingGroup title="Cache Time" description="How long data is kept in cache (minutes)">
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="1"
                        max="60"
                        value={settings.queryCacheTime / 60000}
                        onChange={(e) => onUpdate('queryCacheTime', parseInt(e.target.value) * 60000)}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-20">{settings.queryCacheTime / 60000} min</span>
                </div>
            </SettingGroup>
        </div>
    );
}

// Gallery Settings Component
function GallerySettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-semibold">Gallery Settings</h2>
                <button onClick={onReset} className="text-sm text-gray-400 hover:text-white flex items-center gap-1">
                    <RotateCcw size={14} /> Reset
                </button>
            </div>

            <SettingGroup title="Items Per Page" description="Number of items to load per page">
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="10"
                        max="100"
                        step="10"
                        value={settings.itemsPerPage}
                        onChange={(e) => onUpdate('itemsPerPage', parseInt(e.target.value))}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-16">{settings.itemsPerPage}</span>
                </div>
            </SettingGroup>

            <SettingGroup title="Auto-Refresh on Job Complete" description="Automatically refresh gallery when a generation completes">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={settings.autoRefreshOnJobComplete}
                        onChange={(e) => onUpdate('autoRefreshOnJobComplete', e.target.checked)}
                        className="w-5 h-5 rounded bg-gray-700 border-gray-600 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-300">Enabled</span>
                </label>
            </SettingGroup>

            <SettingGroup title="Silent Refresh" description="Refresh without showing loading indicators">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={settings.silentRefresh}
                        onChange={(e) => onUpdate('silentRefresh', e.target.checked)}
                        className="w-5 h-5 rounded bg-gray-700 border-gray-600 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-300">Enabled</span>
                </label>
            </SettingGroup>
        </div>
    );
}

// Models Settings Component
function ModelsSettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-semibold">Model Manager Settings</h2>
                <button onClick={onReset} className="text-sm text-gray-400 hover:text-white flex items-center gap-1">
                    <RotateCcw size={14} /> Reset
                </button>
            </div>

            <SettingGroup title="Items Per Page" description="Number of models to display per page">
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min="10"
                        max="100"
                        step="10"
                        value={settings.itemsPerPage}
                        onChange={(e) => onUpdate('itemsPerPage', parseInt(e.target.value))}
                        className="w-full md:w-64"
                    />
                    <span className="text-white font-medium w-16">{settings.itemsPerPage}</span>
                </div>
            </SettingGroup>

            <SettingGroup title="Auto-Sync Models" description="Automatically sync models with Modal Volume">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={settings.autoSync}
                        onChange={(e) => onUpdate('autoSync', e.target.checked)}
                        className="w-5 h-5 rounded bg-gray-700 border-gray-600 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-300">Enabled</span>
                </label>
            </SettingGroup>

            <SettingGroup title="Auto-Remove Downloads" description="Automatically remove download status after completion">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={settings.autoRemoveDownloads}
                        onChange={(e) => onUpdate('autoRemoveDownloads', e.target.checked)}
                        className="w-5 h-5 rounded bg-gray-700 border-gray-600 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-300">Enabled</span>
                </label>
            </SettingGroup>
        </div>
    );
}

// Generator Settings Component
function GeneratorSettings({ settings, onUpdate, onReset }) {
    return (
        <div className="space-y-6">
            <div className="flex justify-between items-center mb-4">
                <h2 className="text-xl font-semibold">Generator Settings</h2>
                <button onClick={onReset} className="text-sm text-gray-400 hover:text-white flex items-center gap-1">
                    <RotateCcw size={14} /> Reset
                </button>
            </div>

            <SettingGroup title="Auto-Randomize Seed" description="Automatically randomize seed after each generation">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={settings.autoRandomizeSeed}
                        onChange={(e) => onUpdate('autoRandomizeSeed', e.target.checked)}
                        className="w-5 h-5 rounded bg-gray-700 border-gray-600 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-300">Enabled</span>
                </label>
            </SettingGroup>

            <SettingGroup title="Redirect After Generate" description="Redirect to gallery after starting generation">
                <label className="flex items-center gap-2 cursor-pointer">
                    <input
                        type="checkbox"
                        checked={settings.redirectAfterGenerate}
                        onChange={(e) => onUpdate('redirectAfterGenerate', e.target.checked)}
                        className="w-5 h-5 rounded bg-gray-700 border-gray-600 text-blue-600 focus:ring-blue-500"
                    />
                    <span className="text-sm text-gray-300">Enabled</span>
                </label>
            </SettingGroup>

            {settings.redirectAfterGenerate && (
                <SettingGroup title="Redirect Delay" description="Delay before redirecting (milliseconds)">
                    <div className="flex items-center gap-4">
                        <input
                            type="range"
                            min="0"
                            max="5000"
                            step="500"
                            value={settings.redirectDelay}
                            onChange={(e) => onUpdate('redirectDelay', parseInt(e.target.value))}
                            className="w-full md:w-64"
                        />
                        <span className="text-white font-medium w-20">{settings.redirectDelay}ms</span>
                    </div>
                </SettingGroup>
            )}
        </div>
    );
}

// Reusable Setting Group Component
function SettingGroup({ title, description, children, action }) {
    return (
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 pb-6 border-b border-gray-700/50 last:border-0">
            <div className="flex-1">
                <div className="flex items-center gap-2">
                    <h3 className="font-medium text-white">{title}</h3>
                    {action}
                </div>
                <p className="text-sm text-gray-400 mt-1">{description}</p>
            </div>
            <div className="md:ml-4">
                {children}
            </div>
        </div>
    );
}
