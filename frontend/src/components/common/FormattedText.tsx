import React from 'react';

/**
 * Strips raw JSON strings, code blocks, or nested objects to return clean reply text.
 */
export function cleanAiMessageText(input: any): string {
  if (input === null || input === undefined) return '';
  if (typeof input === 'object') {
    return input.reply || input.text || input.message || JSON.stringify(input);
  }
  let str = String(input).trim();

  // Strip ```json ... ``` markdown block wrappers
  if (str.startsWith('```')) {
    str = str.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  }

  // Handle raw JSON string like {"reply": "..."}
  if (str.startsWith('{') && str.endsWith('}')) {
    try {
      const parsed = JSON.parse(str);
      if (parsed && typeof parsed === 'object') {
        return parsed.reply || parsed.text || parsed.message || str;
      }
    } catch {
      // Ignore parse failure, proceed with raw text
    }
  }

  return str;
}

interface FormattedTextProps {
  content: any;
  className?: string;
  isUserMessage?: boolean;
}

export const FormattedText: React.FC<FormattedTextProps> = ({ content, className = '', isUserMessage = false }) => {
  const text = cleanAiMessageText(content);
  if (!text) return null;

  // Split content into paragraphs by double line breaks
  const paragraphs = text.split(/\n\n+/);

  return (
    <div className={`space-y-2.5 leading-relaxed text-sm ${className}`}>
      {paragraphs.map((paragraph, pIdx) => {
        const lines = paragraph.split('\n').filter(line => line.trim().length > 0);

        // Check if all non-empty lines in paragraph are list items (1., 2., -, *)
        const isList = lines.length > 0 && lines.every(line => /^\s*(\d+[.)]|[-*•])\s+/.test(line));

        if (isList) {
          return (
            <ul key={pIdx} className="space-y-2 my-1.5 pl-0">
              {lines.map((line, lIdx) => {
                const match = line.match(/^\s*(\d+[.)]|[-*•])\s+(.*)/);
                const prefix = match ? match[1] : '';
                const body = match ? match[2] : line;
                const isNumber = /^\d+/.test(prefix);

                return (
                  <li key={lIdx} className="flex items-start gap-2 text-sm">
                    {isNumber ? (
                      <span className={`font-extrabold text-[11px] px-1.5 py-0.5 rounded-md shrink-0 mt-0.5 ${
                        isUserMessage
                          ? 'bg-[#355F58]/20 text-[#355F58] border border-[#355F58]/30'
                          : 'bg-[#355F58]/10 text-[#355F58] border border-[#355F58]/20'
                      }`}>
                        {prefix}
                      </span>
                    ) : (
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 mt-2 ${
                        isUserMessage ? 'bg-[#355F58]' : 'bg-[#487C74]'
                      }`} />
                    )}
                    <span className="flex-1 min-w-0">
                      {renderInlineFormatting(body, isUserMessage)}
                    </span>
                  </li>
                );
              })}
            </ul>
          );
        }

        return (
          <p key={pIdx} className="leading-relaxed">
            {lines.map((line, lIdx) => {
              // Check if line itself starts as a single list item
              const singleMatch = line.match(/^\s*(\d+[.)]|[-*•])\s+(.*)/);
              if (singleMatch) {
                const prefix = singleMatch[1];
                const body = singleMatch[2];
                const isNumber = /^\d+/.test(prefix);
                return (
                  <span key={lIdx} className="flex items-start gap-2 text-sm my-1">
                    {isNumber ? (
                      <span className={`font-extrabold text-[11px] px-1.5 py-0.5 rounded-md shrink-0 mt-0.5 ${
                        isUserMessage
                          ? 'bg-[#355F58]/20 text-[#355F58] border border-[#355F58]/30'
                          : 'bg-[#355F58]/10 text-[#355F58] border border-[#355F58]/20'
                      }`}>
                        {prefix}
                      </span>
                    ) : (
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 mt-2 ${
                        isUserMessage ? 'bg-[#355F58]' : 'bg-[#487C74]'
                      }`} />
                    )}
                    <span className="flex-1 min-w-0">
                      {renderInlineFormatting(body, isUserMessage)}
                    </span>
                  </span>
                );
              }

              return (
                <React.Fragment key={lIdx}>
                  {lIdx > 0 && <br />}
                  {renderInlineFormatting(line, isUserMessage)}
                </React.Fragment>
              );
            })}
          </p>
        );
      })}
    </div>
  );
};

function renderInlineFormatting(text: string, isUserMessage: boolean): React.ReactNode {
  // Regex to split by bold **text**, *italic*, or `code`
  const parts = text.split(/(\*\*.*?\*\*|\*.*?\*|`.*?`)/g);

  return parts.map((part, idx) => {
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
      return (
        <strong key={idx} className={`font-extrabold ${isUserMessage ? 'text-[#2A4D47]' : 'text-[#1F2522]'}`}>
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return (
        <em key={idx} className="italic text-[#5F6863]">
          {part.slice(1, -1)}
        </em>
      );
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <code key={idx} className="px-1.5 py-0.5 rounded bg-slate-100 font-mono text-xs text-[#355F58] border border-[#D9DEDA]">
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}
