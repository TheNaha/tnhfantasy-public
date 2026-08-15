import React from 'react';
import { motion } from 'framer-motion';
import { FaceSmile } from 'lucide-react';
import { useExpression, useUpdateExpressions } from '../../hooks/useWorldVault';
import toast from 'react-hot-toast';

/**
 * ExpressionSelector — Visual grid of character expressions (avatar emotions).
 * Shows a preview of each expression and allows switching the active one.
 */
export default function ExpressionSelector({ characterId, character, inline = false }) {
    const { data: expressions = {}, isLoading } = useExpression(characterId);
    const { mutate: updateExpressions } = useUpdateExpressions();

    const expressionData = character?.expressions || expressions;

    if (isLoading || !expressionData || Object.keys(expressionData).filter(k => !k.startsWith('_')).length === 0) {
        if (inline) return null;
        return (
            <div className="text-center py-8 text-gray-500">
                <FaceSmile size={32} className="mx-auto mb-2 opacity-30" />
                <p className="text-sm">No expressions configured</p>
            </div>
        );
    }

    const activeExpression = expressionData._active || Object.keys(expressionData).filter(k => !k.startsWith('_'))[0];

    const handleSelect = (expressionKey) => {
        updateExpressions({
            characterId,
            expressions: expressionData,
            active_expression: expressionKey,
        }, {
            onSuccess: () => {
                toast.success(`Switched to ${expressionKey}`);
            },
            onError: (err) => toast.error(`Failed: ${err.message}`),
        });
    };

    const renderGrid = () => {
        const entries = Object.entries(expressionData).filter(([k]) => !k.startsWith('_'));
        return (
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
                {entries.map(([key, val]) => {
                    const expressionObj = typeof val === 'object' ? val : { image: val };
                    const isActive = key === activeExpression;
                    const borderClass = isActive
                        ? 'border-blue-500 ring-2 ring-blue-500/30'
                        : 'border-gray-700 hover:border-gray-600';
                    const labelClass = isActive
                        ? 'bg-blue-500/20 text-blue-300'
                        : 'bg-gray-900/80 text-gray-400';

                    return (
                        <motion.button
                            key={key}
                            whileHover={{ scale: 1.05 }}
                            onClick={() => handleSelect(key)}
                            className={`relative rounded-xl border-2 transition-all overflow-hidden ${borderClass} bg-gray-800 aspect-square`}
                        >
                            {expressionObj.image ? (
                                <img
                                    src={expressionObj.image}
                                    alt={key}
                                    className="w-full h-full object-cover"
                                />
                            ) : (
                                <div className="w-full h-full flex items-center justify-center">
                                    <FaceSmile size={24} className="text-gray-500" />
                                </div>
                            )}
                            <div className={`absolute bottom-0 left-0 right-0 py-1 text-xs font-medium text-center ${labelClass}`}>
                                {key}
                            </div>
                        </motion.button>
                    );
                })}
            </div>
        );
    };

    if (inline) {
        return <div className="mt-4">{renderGrid()}</div>;
    }

    return (
        <div className="p-4">
            <div className="flex items-center gap-2 mb-4">
                <FaceSmile size={20} className="text-gray-400" />
                <h3 className="font-medium text-white">Expressions</h3>
            </div>
            {renderGrid()}
        </div>
    );
}
