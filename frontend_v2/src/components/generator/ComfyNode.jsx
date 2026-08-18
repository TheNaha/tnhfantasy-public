import React, { memo } from 'react';
import { Handle, Position, useReactFlow } from '@xyflow/react';
import { Trash2 } from 'lucide-react';
import { useRegistry } from './RegistryContext';

function ComfyNode({ id, data, selected }) {
  const { nodeType } = data;
  const registry = useRegistry();
  const { setNodes, setEdges } = useReactFlow();
  
  if (!registry) return <div className="p-2 bg-red-500 rounded">No registry</div>;

  const def = registry.getNodeDef(nodeType);
  if (!def) return <div className="p-2 bg-red-500 rounded">Unknown Node</div>;

  const { required, optional } = registry.getInputs(nodeType);
  const outputs = registry.getOutputs(nodeType);

  // ComfyUI distinguishes between widget inputs (like strings/ints) and node inputs (links).
  // Primitives (INT, FLOAT, STRING, BOOLEAN) are rendered as editable inputs below.
  const inputKeys = [...Object.keys(required), ...Object.keys(optional)];
  
  return (
    <div className={`rounded-xl shadow-xl min-w-[240px] border-2 transition-colors bg-[#111827] ${selected ? 'border-blue-500 shadow-[0_0_15px_rgba(59,130,246,0.3)]' : 'border-white/10'}`}>
      {/* Header */}
      <div className="px-3 py-2 bg-gradient-to-r from-gray-800 to-gray-900 border-b border-white/5 flex items-center justify-between rounded-t-xl group">
        <span className="font-bold text-sm text-gray-200 tracking-wide">{def.display_name || nodeType}</span>
        <button 
          className="text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
          onClick={() => {
            setNodes((nds) => nds.filter(n => n.id !== id));
            setEdges((eds) => eds.filter(e => e.source !== id && e.target !== id));
          }}
          title="Delete Node"
        >
          <Trash2 size={16} />
        </button>
      </div>

      {/* Body */}
      <div className="p-3 flex flex-col gap-3 rounded-b-xl">
        
        {/* Node Handles & Inputs */}
        <div className="flex justify-between gap-6">
          <div className="flex flex-col gap-2 w-full">
          {inputKeys.map((key) => {
            const inputDef = required[key] || optional[key];
            const isWidget = Array.isArray(inputDef) && Array.isArray(inputDef[0]);
            const isPrimitive = Array.isArray(inputDef) && ['INT', 'FLOAT', 'STRING', 'BOOLEAN'].includes(inputDef[0]);
            
            if (isWidget || isPrimitive) {
              const type = isWidget ? 'dropdown' : inputDef[0];
              const defaultValue = inputDef[1]?.default ?? '';
              
              return (
                <div key={key} className="flex flex-col gap-1 mt-1">
                  <span className="text-xs text-gray-400 font-medium">{key}</span>
                  {type === 'dropdown' ? (
                    <select className="nodrag w-full bg-gray-900 border border-gray-700 rounded text-xs p-1 text-gray-300 focus:border-blue-500 outline-none">
                      {inputDef[0].map(opt => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                  ) : type === 'BOOLEAN' ? (
                    <input type="checkbox" className="nodrag w-4 h-4 bg-gray-900 border border-gray-700 rounded" defaultChecked={defaultValue} />
                  ) : (
                    <input 
                      type={type === 'INT' || type === 'FLOAT' ? 'number' : 'text'} 
                      className="nodrag w-full bg-gray-900 border border-gray-700 rounded text-xs p-1 text-gray-300 focus:border-blue-500 outline-none"
                      defaultValue={defaultValue}
                      step={type === 'FLOAT' ? "0.01" : "1"}
                    />
                  )}
                </div>
              );
            }
            
            // It's a standard graph Handle (e.g. MODEL, CONDITIONING, LATENT)
            return (
              <div key={key} className="relative flex items-center h-6">
                <Handle
                  type="target"
                  position={Position.Left}
                  id={key}
                  className="w-3 h-3 bg-blue-500 border-2 border-gray-900 !left-[-18px]"
                />
                <span className="text-xs text-gray-300 font-medium ml-1">{key}</span>
              </div>
            );
          })}
        </div>

        {/* Outputs (Right) */}
        <div className="flex flex-col gap-2 items-end">
          {outputs.map((out, idx) => (
            <div key={`${out.name}_${idx}`} className="relative flex items-center justify-end h-6">
              <span className="text-xs text-gray-300 font-medium mr-1">{out.name}</span>
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
    </div>
  );
}

export default memo(ComfyNode);
