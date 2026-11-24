import React from 'react';
import { GoogleMapsAttribution } from './GoogleMapsAttribution';
import { creditLabel, type ImageCreditInfo } from '../../utils/imageSources';

interface ImageCreditProps extends ImageCreditInfo {
  className?: string;
}

/**
 * The credit chip for a picture: the Google photo author plus "Google Maps", "Wikimedia Commons (CC BY-SA)",
 * or "Photo by X on Pexels", linked to the source page. Nothing for pictures that need no credit.
 * Meant to sit over the image corner (dark chip, white text).
 */
export const ImageCredit: React.FC<ImageCreditProps> = ({ source, credit, creditUrl, className = '' }) => {
  const label = creditLabel({ source, credit });
  if (!label) return null;
  const safeUrl = creditUrl && /^https:\/\//i.test(creditUrl) ? creditUrl : null;
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded-md bg-black/60 px-1.5 py-0.5 text-[10px] leading-tight text-white ${className}`}
    >
      {safeUrl ? (
        <a
          href={safeUrl}
          target="_blank"
          rel="noopener noreferrer nofollow"
          className="truncate underline-offset-2 hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          {label}
        </a>
      ) : (
        <span className="truncate">{label}</span>
      )}
      {source === 'google' && (
        <>
          <span aria-hidden>·</span>
          <GoogleMapsAttribution className="text-white text-[10px] shrink-0" />
        </>
      )}
    </span>
  );
};
