import { getLocalDateString } from "./utils";

interface BuildEventDetailHrefOptions {
  eventId: string;
  date?: string | null;
  commenceTime?: string | null;
  player?: string | null;
  market?: string | null;
  threshold?: number | string | null;
}

export const buildEventDetailHref = ({
  eventId,
  date,
  commenceTime,
  player,
  market,
  threshold,
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
  return queryString ? `/event/${eventId}?${queryString}` : `/event/${eventId}`;
};
