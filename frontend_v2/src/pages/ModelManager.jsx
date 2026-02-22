import { useState } from 'react';
import { HardDrive, Globe } from 'lucide-react';
import ConfirmationModal from '../components/ConfirmationModal';

// Extracted Components
import { DiscoverTab, InstalledTab } from '../components/model-manager';

export default function ModelManager() {
    const [activeTab, setActiveTab] = useState('discover');
    const [confirmModal, setConfirmModal] = useState({
        isOpen: false,
        title: '',
        message: '',
        onConfirm: () => { },
        isDangerous: false
    });

    return (
        <div className="min-h-screen bg-gray-900 text-white p-4 lg:p-8 relative">
            <div className="max-w-7xl mx-auto space-y-6">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                    <div>
                        <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500">
                            Model Browser
                        </h1>
                        <p className="text-gray-400 mt-1">Discover and manage your ComfyUI models</p>
                    </div>

                    <div className="flex gap-4 items-center">
                        {/* Tabs */}
                        <div className="flex bg-gray-800 p-1 rounded-lg">
                            <button
                                onClick={() => setActiveTab('discover')}
                                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 ${activeTab === 'discover' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                            >
                                <Globe size={16} /> Discover
                            </button>
                            <button
                                onClick={() => setActiveTab('installed')}
                                className={`px-4 py-2 rounded-md text-sm font-medium transition-colors flex items-center gap-2 ${activeTab === 'installed' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'}`}
                            >
                                <HardDrive size={16} /> Installed
                            </button>
                        </div>
                    </div>
                </div>

                {/* Content */}
                <div className="bg-gray-800/50 rounded-2xl border border-gray-700 min-h-[600px] p-6">
                    {activeTab === 'discover' ? (
                        <DiscoverTab />
                    ) : (
                        <InstalledTab openConfirm={(config) => setConfirmModal({ ...config, isOpen: true })} />
                    )}
                </div>
            </div>

            <ConfirmationModal
                isOpen={confirmModal.isOpen}
                onClose={() => setConfirmModal(prev => ({ ...prev, isOpen: false }))}
                onConfirm={confirmModal.onConfirm}
                title={confirmModal.title}
                message={confirmModal.message}
                isDangerous={confirmModal.isDangerous}
                confirmText={confirmModal.confirmText}
            />
        </div>
    );
}

