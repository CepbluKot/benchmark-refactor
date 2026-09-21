import React from 'react';
import { HelpCircle } from 'lucide-react';

export function FieldTooltip({ content }: { content: string }) {
  return (
    <div className="group relative inline-flex items-center ml-2 align-middle">
      <HelpCircle className="w-3.5 h-3.5 text-gray-400 hover:text-indigo-500 transition-colors cursor-help" />
      <div className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-max max-w-[220px] invisible opacity-0 scale-95 translate-y-1 group-hover:visible group-hover:opacity-100 group-hover:scale-100 group-hover:translate-y-0 transition-all duration-200 delay-150 z-50">
        <div className="bg-slate-800 text-white text-[11px] font-medium rounded py-1.5 px-2.5 shadow-lg break-words whitespace-normal text-center leading-snug">
          {content}
          <svg className="absolute text-slate-800 h-1.5 w-full left-0 top-full" x="0px" y="0px" viewBox="0 0 255 255" xmlSpace="preserve"><polygon className="fill-current" points="0,0 127.5,127.5 255,0"/></svg>
        </div>
      </div>
    </div>
  );
}
