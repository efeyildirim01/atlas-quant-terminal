"use client";

import type { ReactNode } from "react";

/**
 * Minimal, safe markdown for model answers: headings, bullets, numbered lists, bold, paragraphs, and [E#] citation
 * chips. Model text is never injected as HTML.
 */
const INLINE = /(\*\*[^*]+\*\*|\[E\d+(?:\s*,\s*E\d+)*\])/g;

export function citationsIn(text: string): string[] {
  return [...text.matchAll(/\[(E\d+(?:\s*,\s*E\d+)*)\]/g)].flatMap((m) => m[1].split(",").map((s) => s.trim()));
}

function inline(text: string, onCite: (id: string) => void, known: Set<string>): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (/^\[E\d+/.test(part)) {
      return (
        <span key={i} className="whitespace-nowrap">
          {citationsIn(part).map((id) => (
            <button key={id} type="button" onClick={() => onCite(id)} data-testid="citation"
              className={`mx-0.5 rounded px-1 font-mono text-[10.5px] ring-1 ${known.has(id) ? "bg-accent/15 text-accent ring-accent/40 hover:bg-accent/25" : "bg-down/15 text-down ring-down/40"}`}
              title={known.has(id) ? `Show evidence ${id}` : `${id} does not exist`}>
              {id}
            </button>
          ))}
        </span>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export function AnswerMarkdown({ text, onCite, known }: { text: string; onCite: (id: string) => void; known: Set<string> }) {
  const blocks: ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const items = list.items.map((it, i) => <li key={i}>{inline(it, onCite, known)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length} className="list-decimal space-y-1 pl-5">{items}</ol> : <ul key={blocks.length} className="list-disc space-y-1 pl-5">{items}</ul>);
    list = null;
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (bullet || numbered) {
      const ordered = !!numbered;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]);
      continue;
    }
    flush();
    if (!line.trim()) continue;
    if (heading) {
      blocks.push(<h3 key={blocks.length} className="mt-2 text-[13.5px] font-semibold text-fg">{inline(heading[2], onCite, known)}</h3>);
    } else {
      blocks.push(<p key={blocks.length}>{inline(line, onCite, known)}</p>);
    }
  }
  flush();
  return <div className="space-y-2 text-[13px] leading-relaxed" data-testid="answer">{blocks}</div>;
}
