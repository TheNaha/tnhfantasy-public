import { HardDrive } from 'lucide-react';
import { useConfirmation } from '../store/confirmationStore';
import { useSettings } from '../store/settingsStore';
import { InstalledTab } from '../components/model-manager';

export default function InstalledModels() {
    const settings = useSettings();
    const { confirm } = useConfirmation();

    return (
        <div className="min-h-screen bg-gray-900 text-white p-4 lg:p-8 relative">
            <div className="max-w-7xl mx-auto space-y-6">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                    <div>
                        <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-500 flex items-center gap-3">
                            <HardDrive size={28} className="text-blue-400" />
                            Installed Models
                        </h1>
                        <p className="text-gray-400 mt-1">Manage your locally installed ComfyUI models</p>
                    </div>
                </div>

                {/* Content */}
                <div className="bg-gray-800/50 rounded-2xl border border-gray-700 min-h-[600px] p-6">
                    <InstalledTab
                        itemsPerPage={settings.models.itemsPerPage}
                        openConfirm={confirm}
                    />
                </div>
            </div>
        </div>
    );
}
