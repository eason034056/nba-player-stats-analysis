import { injuryPaint, type InjuryTag } from "@/lib/injury-tag";
import { cn } from "@/lib/utils";

export function InjuryStatusTag({ tag }: { tag: InjuryTag }) {
  const paint = injuryPaint(tag.tone);
  return (
    <span
      data-injury-tone={tag.tone}
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold",
        paint.chip,
      )}
    >
      <span className="sr-only">Injury: </span>
      <span>{tag.text}</span>
    </span>
  );
}
