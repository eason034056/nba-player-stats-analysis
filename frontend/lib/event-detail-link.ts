import { getLocalDateString } from "./utils";

/**
 * League segment for the event-detail URL. NBA-only on origin/dev pre-SPO-33;
 * SPO-33 adds "wnba" to expose `/wnba/event/[eventId]` while leaving every
 * existing NBA call site untouched (default = `"nba"`).
 */
export type LeagueSegment = "nba" | "wnba";

interface BuildEventDetailHrefOptions {
  eventId: string;
  date?: string | null;
  commenceTime?: string | null;
  player?: string | null;
  market?: string | null;
  threshold?: number | string | null;
  /**
   * Which league's event page to link to. Defaults to "nba" so every existing
   * NBA caller continues to produce `/event/<id>` paths with no source change.
   * Pass `"wnba"` to produce `/wnba/event/<id>` paths (SPO-33).
   */
  league?: LeagueSegment;
}

export const buildEventDetailHref = ({
  eventId,
  date,
  commenceTime,
  player,
  market,
  threshold,
  league = "nba",
}: BuildEventDetailHrefOptions): string => {
  const params = new URLSearchParams();
  const resolvedDate = date || (commenceTime ? getLocalDateString(commenceTime) : undefined);

  if (resolvedDate) {
    params.set("date", resolvedDate);
  }

  if (player) {
    params.set("player", player);
  }

  if (market) {
    params.set("market", market);
  }

  if (threshold !== undefined && threshold !== null && `${threshold}` !== "") {
    params.set("threshold", `${threshold}`);
  }

  const queryString = params.toString();
  const basePath = league === "wnba" ? `/wnba/event/${eventId}` : `/event/${eventId}`;
  return queryString ? `${basePath}?${queryString}` : basePath;
};
