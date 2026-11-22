/** The server's plain message when Google's map search quota is reached / the key is paused (HTTP 503). */
export const mapSearchErrorMessage = (err: unknown, fallback: string): string => {
  const msg = err instanceof Error ? err.message : '';
  return msg.startsWith('Map search') ? msg : fallback;
};
