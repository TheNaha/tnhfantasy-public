import { useState } from 'react';
import {
    AlertCircle,
    Check,
    CheckCircle2,
    Copy,
    Terminal,
    Wrench,
    X,
} from 'lucide-react';
import toast from 'react-hot-toast';
import { ModalOverlay } from '../common/ModalOverlay';
import { copyToClipboard } from '../../utils/clipboard';

export default function ActionOutputModal({ output, onClose }) {
    const [copied, setCopied] = useState(false);

    if (!output) return null;

    const {
        title = 'Action Output',
        status = 'success',
        message = '',
        details = '',
    } = output;

    const isSuccess = status === 'success';

    const handleCopy = async () => {
        const text = details || message || '';
        if (!text) return;
        const ok = await copyToClipboard(text);
        if (ok) {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
            toast.success('Copied to clipboard');
        }
    };

    return (
        <ModalOverlay isOpen={Boolean(output)} onClose={onClose} className="z-[75] bg-black/85 backdrop-blur-sm">
            <div
                role="dialog"
                aria-modal="true"
                aria-label={title}
                className="bg-gray-900 border border-gray-700/80 rounded-2xl w-full max-w-xl flex flex-col max-h-[85vh] shadow-2xl overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="p-4 border-b border-gray-800 flex items-center justify-between">
                    <div className="flex items-center gap-2.5">
                        <div className="p-2 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400">
                            <Wrench size={18} />
                        </div>
                        <div>
                            <h2 className="text-base font-bold text-white">{title}</h2>
                            <p className="text-xs text-gray-400">Execution Output & Status</p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="p-1.5 hover:bg-gray-800 rounded-lg text-gray-400 hover:text-white transition-colors"
                        aria-label="Close action output dialog"
                    >
                        <X size={18} />
                    </button>
                </div>

                {/* Body */}
                <div className="p-5 overflow-y-auto space-y-4 flex-1">
                    {/* Status Badge */}
                    <div
                        className={`flex items-center gap-3 p-3.5 rounded-xl border text-sm ${
                            isSuccess
                                ? 'bg-emerald-950/40 border-emerald-800/40 text-emerald-300'
                                : 'bg-rose-950/40 border-rose-800/40 text-rose-300'
                        }`}
                    >
                        {isSuccess ? (
                            <CheckCircle2 size={18} className="text-emerald-400 flex-shrink-0" />
                        ) : (
                            <AlertCircle size={18} className="text-rose-400 flex-shrink-0" />
                        )}
                        <span className="font-medium">{message || (isSuccess ? 'Completed successfully' : 'Action failed')}</span>
                    </div>

                    {/* Monospace Output */}
                    {details && (
                        <div className="space-y-1.5">
                            <div className="flex items-center justify-between">
                                <span className="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-1.5">
                                    <Terminal size={14} className="text-blue-400" />
                                    Details
                                </span>
                                <button
                                    type="button"
                                    onClick={handleCopy}
                                    className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 px-2 py-1 rounded-md border border-gray-700 transition-colors"
                                >
                                    {copied ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                                    {copied ? 'Copied' : 'Copy'}
                                </button>
                            </div>
                            <pre className="bg-[#0B0E14] border border-gray-800 rounded-xl p-3.5 max-h-64 overflow-y-auto overflow-x-auto text-xs font-mono text-gray-300 whitespace-pre-wrap select-text leading-relaxed">
                                {details}
                            </pre>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="p-3.5 border-t border-gray-800 bg-gray-900/60 flex items-center justify-end">
                    <button
                        type="button"
                        onClick={onClose}
                        className="px-4 py-2 rounded-xl text-xs font-medium bg-gray-800 hover:bg-gray-700 text-white transition-colors"
                    >
                        Close
                    </button>
                </div>
            </div>
        </ModalOverlay>
    );
}
