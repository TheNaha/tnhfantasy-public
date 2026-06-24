import React, { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

function ComfyNode({ data, selected }) {
  const { nodeType, registry } = data;
  
  if (!registry) return <div className="p-2 bg-red-500 rounded">No registry</div>;

  const def = registry.getNodeDef(nodeType);
  if (!def) return <div className="p-2 bg-red-500 rounded">Unknown Node</div>;

  const { required, optional } = registry.getInputs(nodeType);
  const outputs = registry.getOutputs(nodeType);

  // ComfyUI distinguishes between widget inputs (like strings/ints) and node inputs (links).
  // For simplicity in this v1, we treat everything that isn't a widget as a Handle.
  // In a full implementation, we'd render inputs for primitives.
  const inputKeys = [...Object.keys(required), ...Object.keys(optional)];
  
  return (
    <div className={`rounded-xl shadow-xl overflow-hidden min-w-[200px] border-2 transition-colors ${selected ? 'border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.3)]' : 'border-white/10'}`}>
      {/* Header */}
      <div className="px-3 py-2 bg-gradient-to-r from-gray-800 to-gray-900 border-b border-white/5 flex items-center justify-between">
        <span className="font-bold text-sm text-gray-200 tracking-wide">{def.display_name || nodeType}</span>
      </div>

      {/* Body */}
      <div className="p-3 bg-[#111827]/90 backdrop-blur-xl flex justify-between gap-6">
        
        {/* Inputs (Left) */}
        <div className="flex flex-col gap-2">
          {inputKeys.map((key) => {
            const inputDef = required[key] || optional[key];
            // Also some inputs are lists of strings (dropdowns) -> these are widgets, not handles.
            const isWidget = Array.isArray(inputDef) && Array.isArray(inputDef[0]);
            
            // Only render handles for actual node links
            if (isWidget) return null; // We'd render a select box here in the future
            if (inputDef[0] === 'INT' || inputDef[0] === 'FLOAT' || inputDef[0] === 'STRING' || inputDef[0] === 'BOOLEAN') return null; // Input field
            
            return (
              <div key={key} className="relative flex items-center h-5">
                <Handle
                  type="target"
                  position={Position.Left}
                  id={key}
                  className="w-3 h-3 bg-blue-500 border-2 border-gray-900 !left-[-18px]"
                />
                <span className="text-xs text-gray-400 font-medium">{key}</span>
              </div>
            );
          })}
        </div>

        {/* Outputs (Right) */}
        <div className="flex flex-col gap-2 items-end">
          {outputs.map((out, idx) => (
            <div key={`${out.name}_${idx}`} className="relative flex items-center justify-end h-5">
              <span className="text-xs text-gray-400 font-medium">{out.name}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={String(idx)} // ComfyUI uses array indices for output links
                className="w-3 h-3 bg-purple-500 border-2 border-gray-900 !right-[-18px]"
              />
            </div>
          ))}
        </div>

      </div>
    </div>
  );
}

export default memo(ComfyNode);
