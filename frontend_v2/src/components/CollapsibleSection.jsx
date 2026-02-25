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
        <div className={`border-b border-gray-800 ${className}`}>
            <h3>
                <button
                    type="button"
                    id={headerId}
                    aria-expanded={isOpen}
                    aria-controls={contentId}
                    onClick={() => setIsOpen(!isOpen)}
                    className="w-full py-3 flex justify-between items-center hover:bg-gray-800/30 transition-colors rounded-lg focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:outline-none px-2 -mx-2"
                >
                    <span className="text-base lg:text-lg font-semibold flex items-center gap-2">
                        {icon}
                        {title}
                    </span>
                    <ChevronDown
                        size={20}
                        className={`text-gray-400 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
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
