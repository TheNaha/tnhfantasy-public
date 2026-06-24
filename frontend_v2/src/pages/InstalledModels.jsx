import { HardDrive } from 'lucide-react';
import { useConfirmation } from '../store/confirmationStore';
import { useSettings } from '../store/settingsStore';
import { InstalledTab } from '../components/model-manager';

export default function InstalledModels() {
    const settings = useSettings();
    const { confirm } = useConfirmation();

    return (
        <div className="relative w-full">
            <div className="max-w-7xl mx-auto space-y-4 md:space-y-6">
                {/* Header */}
                <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
                    <div>
                        <h1 className="text-2xl md:text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-500 flex items-center gap-3 drop-shadow-md tracking-tight">
                            <HardDrive size={32} className="text-blue-400 drop-shadow-[0_0_10px_rgba(59,130,246,0.6)]" />
                            Installed Models
                        </h1>
                        <p className="text-gray-400 mt-1.5 font-medium tracking-wide">Manage your locally installed ComfyUI models</p>
                    </div>
                </div>

                {/* Content */}
                <div className="glass-panel rounded-3xl border border-white/5 min-h-[600px] p-4 md:p-6 shadow-2xl relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-96 h-96 bg-blue-500/10 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 pointer-events-none" />
                    <div className="absolute bottom-0 left-0 w-96 h-96 bg-purple-500/10 rounded-full blur-3xl translate-y-1/2 -translate-x-1/2 pointer-events-none" />
                    <div className="relative z-10">
                        <InstalledTab
                            itemsPerPage={settings.models.itemsPerPage}
                            openConfirm={confirm}
                        />
                    </div>
                </div>
            </div>
        </div>
    );
}
