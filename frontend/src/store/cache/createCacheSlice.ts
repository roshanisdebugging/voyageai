import {
  createSlice,
  type ActionReducerMapBuilder,
  type PayloadAction,
  type Slice,
  type SliceCaseReducers,
} from '@reduxjs/toolkit';
import { createInitialCacheState, type CacheState } from './cacheTypes';
import { resetAllCaches } from './globalActions';

export interface CacheSliceOptions<
  T,
  Extra extends object,
  R extends SliceCaseReducers<CacheState<T> & Extra>,
> {
  name: string;
  selectId: (item: T) => string;
  extraInitialState?: Extra;
  /** Slice-specific reducers, added next to the standard ones. */
  reducers?: R;
  extraReducers?: (builder: ActionReducerMapBuilder<CacheState<T> & Extra>) => void;
}

/**
 * Standard cache slice. Every cache slice exposes the same state shape and
 * actions: set, upsert, remove, clear, invalidate (+ setLoading, setError),
 * and all of them reset on the global `cache/resetAll` action.
 *
 * Curried so the item/extra-state types are given explicitly while the custom reducers are
 * still inferred:  createCacheSlice<Trip, TripsExtra>()({ name, selectId, reducers, ... })
 *
 * The standard reducers take `state: any` and cast internally, and the finished slice is cast
 * once at the createSlice boundary: Immer's Draft<> of a generic state type does not unify with
 * a plain CacheState<T> parameter, and RTK's reducer validation rejects it.
 */
export function createCacheSlice<T, Extra extends object = Record<never, never>>() {
  type S = CacheState<T> & Extra;

  return function build<R extends SliceCaseReducers<S> = Record<never, never>>(
    opts: CacheSliceOptions<T, Extra, R>,
  ) {
    const initialState = {
      ...createInitialCacheState<T>(),
      ...(opts.extraInitialState ?? {}),
    } as S;

    const standard = {
      set(state: any, action: PayloadAction<T[]>) {
        const s = state as CacheState<T>;
        s.data = action.payload;
        s.isInitialized = true;
        s.loading = false;
        s.error = null;
        s.lastFetchedAt = Date.now();
      },
      upsert(state: any, action: PayloadAction<T | T[]>) {
        const data = (state as CacheState<T>).data;
        const items = Array.isArray(action.payload) ? action.payload : [action.payload];
        for (const item of items) {
          const id = opts.selectId(item);
          const idx = data.findIndex((d) => opts.selectId(d) === id);
          if (idx >= 0) data[idx] = item;
          else data.push(item);
        }
      },
      remove(state: any, action: PayloadAction<string | string[]>) {
        const s = state as CacheState<T>;
        const ids = new Set(Array.isArray(action.payload) ? action.payload : [action.payload]);
        s.data = s.data.filter((d) => !ids.has(opts.selectId(d)));
      },
      clear(): S {
        return initialState;
      },
      /** Marks data stale so the next mount refetches. Keeps data so the UI stays populated. */
      invalidate(state: any) {
        (state as CacheState<T>).isInitialized = false;
      },
      setLoading(state: any, action: PayloadAction<boolean>) {
        (state as CacheState<T>).loading = action.payload;
      },
      setError(state: any, action: PayloadAction<string | null>) {
        const s = state as CacheState<T>;
        s.error = action.payload;
        s.loading = false;
      },
    };

    const reducers = { ...standard, ...(opts.reducers ?? {}) } as typeof standard & R;

    const slice = createSlice({
      name: opts.name,
      initialState,
      reducers: reducers as any,
      extraReducers: (builder) => {
        builder.addCase(resetAllCaches, () => initialState);
        opts.extraReducers?.(builder as unknown as ActionReducerMapBuilder<S>);
      },
    }) as unknown as Slice<S, typeof standard & R, string>;

    return { slice, initialState };
  };
}
