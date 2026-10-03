import React, { useState } from 'react';
import { Search, ChevronRight, ChevronDown } from 'lucide-react';

export default function NodeSidebar({ registry }) {
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedCategories, setExpandedCategories] = useState({});

  if (!registry) return null;

  const categories = registry.getCategories();

  const toggleCategory = (cat) => {
    setExpandedCategories(prev => ({ ...prev, [cat]: !prev[cat] }));
  };

  const onDragStart = (event, nodeType) => {
    event.dataTransfer.setData('application/reactflow', nodeType);
    event.dataTransfer.effectAllowed = 'move';
  };

  // Filter nodes based on search
  const filteredCategories = {};
  Object.keys(categories).forEach(cat => {
    const nodes = categories[cat].filter(node => 
      node.type.toLowerCase().includes(searchTerm.toLowerCase()) || 
      (node.display_name && node.display_name.toLowerCase().includes(searchTerm.toLowerCase()))
    );
    if (nodes.length > 0) {
      filteredCategories[cat] = nodes;
    }
  });

  return (
    // `w-64 sm:w-64`, not a bare `w-64`. This sidebar has no responsive
    // variant, so inside the `flex` shell at `ReactFlowEditor.jsx:127` it took a
    // fixed 256px of a 312px row and left the graph canvas 54px wide at 360
    // (84px at 390, 124px at 430) — against `ComfyNode.jsx`'s `min-w-[240px]`,
    // so every node was 4.4x wider than the canvas meant to hold it. The 202px
    // minimap was wider than that canvas and painted over the palette. Full
    // width below `sm`, which stacks the palette above the graph instead of
    // beside it.
    <div className="w-full sm:w-64 h-full max-h-56 sm:max-h-none bg-[#0B0E14] border-r sm:border-b border-white/10 flex flex-col z-10">
      <div className="p-3 border-b border-white/10">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 text-gray-500" size={16} />
          <input
            type="text"
            aria-label="Search nodes" placeholder="Search nodes..."
            className="w-full bg-[#111827] border border-white/10 rounded-lg pl-9 pr-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-blue-500 transition-colors"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>
      
      <div className="flex-1 overflow-y-auto p-2 scrollbar-thin scrollbar-thumb-gray-800 scrollbar-track-transparent">
        {Object.entries(filteredCategories).sort(([a], [b]) => a.localeCompare(b)).map(([category, nodes]) => {
          const isExpanded = !!expandedCategories[category] || searchTerm !== '';
          
          return (
            <div key={category} className="mb-1">
              <button
                onClick={() => toggleCategory(category)}
                className="w-full flex items-center gap-2 p-2 text-sm font-medium text-gray-400 hover:text-gray-200 hover:bg-white/5 rounded-md transition-colors"
              >
                {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <span className="truncate">{category}</span>
                <span className="ml-auto text-xs opacity-50">{nodes.length}</span>
              </button>
              
              {isExpanded && (
                <div className="ml-4 mt-1 space-y-1">
                  {nodes.map(node => (
                    <div
                      key={node.type}
                      onDragStart={(e) => onDragStart(e, node.type)}
                      draggable
                      className="p-2 text-xs text-gray-300 bg-[#111827] border border-white/5 hover:border-blue-500/50 hover:bg-[#1A2333] rounded cursor-grab active:cursor-grabbing truncate transition-colors"
                      title={node.description || node.type}
                    >
                      {node.display_name || node.type}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
        {Object.keys(filteredCategories).length === 0 && (
          <div className="p-4 text-center text-gray-500 text-sm">
            No nodes found
          </div>
        )}
      </div>
    </div>
  );
}
