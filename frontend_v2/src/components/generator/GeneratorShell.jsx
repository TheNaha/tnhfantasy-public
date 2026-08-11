import { Loader2 } from 'lucide-react';
import GeneratorTabs from './GeneratorTabs';
import MissingModelsDialog from './MissingModelsDialog';

/**
 * Shared page shell for the guided generator pages (Simple / Img2Img / Inpaint).
 * Owns the header (Create + queue badge + tabs), the 3-column grid, and the
 * missing-models dialog that all three pages render identically.
 */
export default function GeneratorShell({
    accentClass,
    activeJobCount,
    leftColumn,
    rightColumn,
    leftColumnClass = '',
    rightColumnClass = '',
    gapClass = 'gap-4 lg:gap-8',
    isMissingModelsOpen,
    setIsMissingModelsOpen,
    validationResult,
}) {
    return (
        <div className="pb-24">
            <div className="max-w-6xl mx-auto mb-6">
                <div className="flex justify-between items-center mb-4">
                    <h1 className={`text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r ${accentClass}`}>
                        Create
                    </h1>
                    {activeJobCount > 0 && (
                        <div className="flex items-center gap-2 bg-blue-900/30 text-blue-200 px-3 py-1.5 rounded-full text-sm border border-blue-800/50 backdrop-blur-sm">
                            <Loader2 className="animate-spin" size={14} />
                            <span>{activeJobCount} in queue</span>
                        </div>
                    )}
                </div>
                <GeneratorTabs />
            </div>

            <div className={`max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 ${gapClass}`}>
                <div className={`lg:col-span-2 space-y-4 lg:space-y-4 md:space-y-6 ${leftColumnClass}`}>
                    {leftColumn}
                </div>
                <div className={`space-y-4 lg:space-y-4 md:space-y-6 ${rightColumnClass}`}>
                    {rightColumn}
                </div>
            </div>

            <MissingModelsDialog
                isOpen={isMissingModelsOpen}
                onClose={() => setIsMissingModelsOpen(false)}
                validationResult={validationResult}
            />
        </div>
    );
}
