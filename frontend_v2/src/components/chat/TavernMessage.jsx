import { memo } from 'react';
import clsx from 'clsx';
import { parseTavernMessage } from '../../utils/tavernUtils';

const TavernMessage = memo(function TavernMessage({ content, alignRight }) {
    const segments = parseTavernMessage(content);
    if (!segments.length) return <span>{content}</span>;
    return (
        <div className={clsx("flex flex-col gap-2.5 w-full", alignRight && "items-end")}>
            {segments.map((seg, i) => {
                if (seg.type === 'action') {
                    return (
                        <div key={i} className="text-gray-400 italic font-medium opacity-90 text-sm px-1 py-0.5 leading-relaxed">
                            {seg.content}
                        </div>
                    );
                }
                if (seg.type === 'speech') {
                    return (
                        <div key={i} className={clsx("px-4 py-3 rounded-2xl bg-gray-800 border border-gray-700/50 text-gray-100 font-medium tracking-wide shadow-sm w-fit max-w-full break-words", alignRight ? "rounded-tr-sm" : "rounded-tl-sm")}>
                            "{seg.content}"
                        </div>
                    );
                }
                return (
                    <div key={i} className={clsx("px-4 py-3 rounded-2xl bg-gray-800/40 border border-gray-700/30 text-gray-300 text-sm shadow-sm w-fit max-w-full break-words leading-relaxed", alignRight ? "rounded-tr-sm" : "rounded-tl-sm")}>
                        {seg.content}
                    </div>
                );
            })}
        </div>
    );
});

export default TavernMessage;
