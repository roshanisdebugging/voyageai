import { createAction } from '@reduxjs/toolkit';

/** Dispatched on logout / 401 / user switch. Every cache slice resets to its initial state. */
export const resetAllCaches = createAction('cache/resetAll');
