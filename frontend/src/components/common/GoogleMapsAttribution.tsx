import React from 'react';

/**
 * "Google Maps" attribution for Google Maps content shown outside a Google map (Google Maps Platform policy:
 * the logo where possible, the text "Google Maps" where space is limited; never modified or hidden).
 * On the Google map itself Google draws its own logo, so this is not needed there.
 */
export const GoogleMapsAttribution: React.FC<{ className?: string }> = ({ className = '' }) => (
  <span
    translate="no"
    className={`notranslate inline-block text-[11px] font-medium tracking-normal ${/text-(?!\[11px\])/.test(className) ? '' : 'text-[#5F6368] dark:text-zinc-400'} ${className}`}
    style={{ fontFamily: 'Roboto, Arial, sans-serif' }}
  >
    Google Maps
  </span>
);
