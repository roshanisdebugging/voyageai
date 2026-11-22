/**
 * HTML for Google advanced markers. Each element is built once; selection only toggles a class,
 * so tapping a pin never rebuilds markers. Styles live in mapView.css (.vg-pin, .vg-cluster, .vg-user, .vg-search).
 */
import { clusterStyle, type PinStyle } from './mapLogic';

/** Category pin: a rounded badge with the category icon, coloured from mapCategoryConfig, dropping in. */
export function createPlacePin(style: PinStyle, title: string, dropDelayMs = 0): HTMLElement {
  const el = document.createElement('div');
  el.className = 'vg-pin vg-pin--drop';
  el.style.setProperty('--pin-color', style.color);
  el.style.setProperty('--pin-ink', style.ink);
  el.style.animationDelay = `${Math.min(dropDelayMs, 900)}ms`;
  el.dataset.category = style.category;
  const badge = document.createElement('div');
  badge.className = 'vg-pin__badge';
  badge.textContent = style.emoji;
  badge.setAttribute('aria-hidden', 'true');
  const tip = document.createElement('div');
  tip.className = 'vg-pin__tip';
  el.append(badge, tip);
  el.title = title;
  return el;
}

export function setPinSelected(el: HTMLElement, selected: boolean): void {
  el.classList.toggle('vg-pin--selected', selected);
}

/** Pulsing dot for the user's live location. */
export function createUserDot(): HTMLElement {
  const el = document.createElement('div');
  el.className = 'vg-user';
  el.innerHTML = '<span class="vg-user__pulse"></span><span class="vg-user__dot"></span>';
  el.setAttribute('aria-label', 'Your location');
  return el;
}

/** The searched (or voice "dikhao") place: a larger glowing pin. */
export function createSearchPin(title: string): HTMLElement {
  const el = document.createElement('div');
  el.className = 'vg-search vg-pin--drop';
  el.innerHTML = '<div class="vg-search__head"></div><div class="vg-search__tip"></div>';
  el.title = title;
  return el;
}

/** Cluster bubble with the count. */
export function createClusterBubble(count: number): HTMLElement {
  const { size, label } = clusterStyle(count);
  const el = document.createElement('div');
  el.className = 'vg-cluster';
  el.style.width = `${size}px`;
  el.style.height = `${size}px`;
  el.textContent = label;
  el.setAttribute('aria-label', `${count} places, tap to zoom in`);
  return el;
}
