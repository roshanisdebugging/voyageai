import type { KeyboardEvent } from 'react';

export function submitOnEnter(event: KeyboardEvent<HTMLFormElement>, submit: () => void) {
  if (event.key === 'Enter' && !event.nativeEvent.isComposing && event.target instanceof HTMLInputElement) {
    event.preventDefault();
    submit();
  }
}
