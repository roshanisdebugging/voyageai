/**
 * Minimal Server-Sent Events parser for fetch() streams (EventSource can't POST or send our headers).
 * Feed it decoded text in any chunk sizes; it calls onEvent once per complete event.
 * Handles "\n" and "\r\n" line ends, events split across chunks, comments (": ...") and multi-line data.
 */
export interface SseEvent {
  event: string;
  data: string;
}

export interface SseParser {
  feed(chunk: string): void;
  /** Call at end of stream: delivers a last event that had no trailing blank line. */
  end(): void;
}

export function createSseParser(onEvent: (e: SseEvent) => void): SseParser {
  let buffer = '';
  let eventName = '';
  let dataLines: string[] = [];

  const dispatch = () => {
    if (dataLines.length > 0) {
      onEvent({ event: eventName || 'message', data: dataLines.join('\n') });
    }
    eventName = '';
    dataLines = [];
  };

  const handleLine = (line: string) => {
    if (line === '') {
      dispatch();
      return;
    }
    if (line.startsWith(':')) return;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') eventName = value;
    else if (field === 'data') dataLines.push(value);
  };

  return {
    feed(chunk: string) {
      buffer += chunk;
      let nl = buffer.indexOf('\n');
      while (nl !== -1) {
        let line = buffer.slice(0, nl);
        if (line.endsWith('\r')) line = line.slice(0, -1);
        buffer = buffer.slice(nl + 1);
        handleLine(line);
        nl = buffer.indexOf('\n');
      }
    },
    end() {
      if (buffer) {
        handleLine(buffer.endsWith('\r') ? buffer.slice(0, -1) : buffer);
        buffer = '';
      }
      dispatch();
    },
  };
}
