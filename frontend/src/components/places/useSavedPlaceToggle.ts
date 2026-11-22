import { useEffect, useMemo, useRef } from 'react';
import { useToast } from '../common/UndoToast';
import { useAppDispatch, useAppSelector } from '../../store/hooks';
import { fetchSavedPlaces, savePlaceThunk, unsavePlaceThunk } from '../../store/reducers/savedPlacesSlice';
import type { SavedPlaceItem } from '../../services/savedPlacesApi';

/**
 * "Save place" for cards that offer it (Home highlights, map cards). Same store and server call as Explore
 * (saved_places, optimistic with rollback), with the Undo toast. Usage:
 *   const saved = useSavedPlaceToggle(); saved.isSaved(id); saved.toggle({ place_id, title, ... })
 */
export function useSavedPlaceToggle() {
  const dispatch = useAppDispatch();
  const { showToast } = useToast();
  const savedPlaces = useAppSelector((s) => s.savedPlaces.data);
  const savedIds = useMemo(() => new Set(savedPlaces.map((p) => p.place_id)), [savedPlaces]);

  // TTL-gated: a no-op while the cached list is fresh.
  useEffect(() => {
    dispatch(fetchSavedPlaces({}));
  }, [dispatch]);

  const toggleRef = useRef<(item: SavedPlaceItem, fromUndo?: boolean) => Promise<void>>(async () => {});
  const toggle = async (item: SavedPlaceItem, fromUndo = false) => {
    const wasSaved = savedIds.has(item.place_id);
    try {
      if (wasSaved) await dispatch(unsavePlaceThunk(item.place_id)).unwrap();
      else await dispatch(savePlaceThunk(item)).unwrap();
      if (!fromUndo) {
        showToast({
          message: wasSaved ? `Removed ${item.title} from saved places` : `Saved ${item.title}`,
          undo: () => toggleRef.current(item, true),
        });
      }
    } catch (err) {
      console.warn('[SAVE PLACE ERROR]', err);
      showToast({ message: "Couldn't update saved places. Please try again.", tone: 'error' });
    }
  };
  useEffect(() => {
    toggleRef.current = toggle;
  });

  return { isSaved: (id: string) => savedIds.has(id), toggle };
}
