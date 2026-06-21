import {
  RefreshCw,
  Download,
  Trash2,
  Loader2,
  Sparkles,
  Image as ImageIcon,
  Paintbrush,
  MoreHorizontal,
  Check
} from "lucide-react";

export default function FeedCardActions({
  item,
  selected,
  selectionMode,
  onSelect,
  reusing,
  remixing,
  imageEndpoint,
  handleReuse,
  handleRemix,
  handleImg2Img,
  handleInpaint,
  onDelete
}) {
  return (
    <div className="absolute top-2 right-2 z-10 flex flex-col gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
      <div className="bg-gray-900/90 backdrop-blur-sm border border-gray-700/50 rounded-xl p-1 shadow-xl flex items-center gap-1">
        {selectionMode ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onSelect(item.name);
            }}
            className={`p-2 rounded-lg ${selected ? "bg-blue-500 text-white" : "bg-gray-700 text-gray-400"}`}
            aria-label={selected ? "Deselect item" : "Select item"}
            aria-pressed={selected}
          >
            <Check size={18} aria-hidden="true" />
          </button>
        ) : (
          <>
            {/* Primary actions - always visible */}
            <button
              onClick={(e) => { e.stopPropagation(); handleReuse(); }}
              disabled={reusing}
              className="p-2 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white disabled:opacity-60 disabled:cursor-not-allowed"
              title="Reuse Parameters"
              aria-label="Reuse Parameters"
            >
              {reusing ? <Loader2 size={18} className="animate-spin" aria-hidden="true" /> : <RefreshCw size={18} aria-hidden="true" />}
            </button>
            <a
              href={imageEndpoint}
              download
              onClick={(e) => e.stopPropagation()}
              className="p-2 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white flex items-center"
              title="Download"
              aria-label="Download"
            >
              <Download size={18} aria-hidden="true" />
            </a>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(item.name);
              }}
              className="p-2 hover:bg-red-900/50 rounded-lg text-gray-400 hover:text-red-400"
              title="Delete"
              aria-label="Delete"
            >
              <Trash2 size={18} aria-hidden="true" />
            </button>

            {/* Secondary actions - visible on md+ screens */}
            <div className="hidden md:flex gap-2">
              <button
                onClick={(e) => { e.stopPropagation(); handleRemix(); }}
                disabled={remixing}
                className="p-2 hover:bg-purple-900/50 rounded-lg text-gray-400 hover:text-purple-400 disabled:opacity-50"
                title="Quick Remix (new seed)"
                aria-label="Quick Remix (new seed)"
              >
                {remixing ? (
                  <Loader2 size={18} className="animate-spin" aria-hidden="true" />
                ) : (
                  <Sparkles size={18} aria-hidden="true" />
                )}
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleImg2Img(); }}
                className="p-2 hover:bg-orange-900/50 rounded-lg text-gray-400 hover:text-orange-400"
                title="Use as Img2Img source"
                aria-label="Use as Img2Img source"
              >
                <ImageIcon size={18} aria-hidden="true" />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); handleInpaint(); }}
                className="p-2 hover:bg-pink-900/50 rounded-lg text-gray-400 hover:text-pink-400"
                title="Inpaint this image"
                aria-label="Inpaint this image"
              >
                <Paintbrush size={18} aria-hidden="true" />
              </button>
            </div>

            {/* Mobile overflow menu - visible only on small screens */}
            <div className="md:hidden relative group/menu">
              <button
                type="button"
                onClick={(e) => e.stopPropagation()}
                className="p-2 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                title="More actions"
                aria-label="More actions"
                aria-haspopup="menu"
              >
                <MoreHorizontal size={18} aria-hidden="true" />
              </button>
              {/* Dropdown menu */}
              <div className="absolute right-0 top-full mt-1 bg-gray-900 border border-gray-700 rounded-lg shadow-xl py-1 z-10 opacity-0 invisible group-focus-within/menu:opacity-100 group-focus-within/menu:visible transition-all min-w-[160px]">
                <button
                  onClick={(e) => { e.stopPropagation(); handleRemix(); }}
                  disabled={remixing}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left text-gray-300 hover:bg-gray-800 disabled:opacity-50"
                >
                  {remixing ? (
                    <Loader2 size={16} className="animate-spin" aria-hidden="true" />
                  ) : (
                    <Sparkles size={16} aria-hidden="true" />
                  )}
                  Remix
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleImg2Img(); }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left text-gray-300 hover:bg-gray-800"
                >
                  <ImageIcon size={16} aria-hidden="true" />
                  Img2Img
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleInpaint(); }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left text-gray-300 hover:bg-gray-800"
                >
                  <Paintbrush size={16} aria-hidden="true" />
                  Inpaint
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
