import { useState, useId } from 'react';
import { ChevronDown } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

/**
 * CollapsibleSection - A reusable accordion component with proper accessibility.
 *
 * @param {string} title - The title of the section
 * @param {React.ReactNode} icon - Optional icon to display before the title
 * @param {boolean} defaultOpen - Whether the section is open by default
 * @param {string} className - Additional classes for the container
 * @param {React.ReactNode} children - The content of the section
 */
const CollapsibleSection = ({ title, icon, defaultOpen = true, children, className = "" }) => {
    const [isOpen, setIsOpen] = useState(defaultOpen);
    const contentId = useId();
    const headerId = useId();

    return (
        <div className={`glass-panel p-5 rounded-2xl border border-white/5 shadow-xl mb-4 ${className}`}>
            <h3>
                <button
                    type="button"
                    id={headerId}
                    aria-expanded={isOpen}
                    aria-controls={contentId}
                    onClick={() => setIsOpen(!isOpen)}
                    className="w-full pb-2 flex justify-between items-center group focus-visible:outline-none"
                >
                    <span className="text-base lg:text-lg font-bold flex items-center gap-2 text-white">
                        {icon}
                        {title}
                    </span>
                    <ChevronDown
                        size={20}
                        className={`text-gray-500 group-hover:text-white transition-all duration-300 ${isOpen ? 'rotate-180' : ''}`}
                        aria-hidden="true"
                    />
                </button>
            </h3>

            <AnimatePresence initial={false}>
                {isOpen && (
                    <motion.div
                        id={contentId}
                        role="region"
                        aria-labelledby={headerId}
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: 'auto', opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                    >
                        <div className="pb-4 pt-2 space-y-4">
                            {children}
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
};

export default CollapsibleSection;
