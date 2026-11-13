import React, { useState } from 'react';
import { optimizeUnsplashUrl } from '../../utils/imageUtils';

interface SafeImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  fallbackSrc?: string;
  containerClassName?: string;
}

/**
 * Safe Image component that handles broken image URLs gracefully without displaying broken browser icons.
 */
export const SafeImage: React.FC<SafeImageProps> = ({
  src,
  alt = 'Image',
  className = 'w-full h-full object-cover',
  fallbackSrc = 'https://images.unsplash.com/photo-1512343879784-a960bf40e7f2?auto=format&fit=crop&w=600&q=80',
  containerClassName = '',
  ...props
}) => {
  const [hasError, setHasError] = useState(false);
  const resolvedFallback = optimizeUnsplashUrl(fallbackSrc, 600, 80);
  const resolvedSrc = src ? optimizeUnsplashUrl(src, 600, 80) : resolvedFallback;
  const [currentSrc, setCurrentSrc] = useState(resolvedSrc);

  const handleError = () => {
    if (!hasError) {
      setHasError(true);
      setCurrentSrc(resolvedFallback);
    }
  };

  if (hasError && currentSrc === resolvedFallback) {
    // Render gradient banner if fallback also fails or network offline
    return (
      <div className={`w-full h-full bg-gradient-to-br from-[#1F2522] via-[#2C504A] to-[#355F58] flex items-center justify-center p-3 text-center ${containerClassName}`}>
        <span className="text-white font-extrabold text-xs tracking-wider uppercase opacity-90 truncate max-w-full">
          {alt}
        </span>
      </div>
    );
  }

  return (
    <img
      src={currentSrc || fallbackSrc}
      alt={alt}
      className={className}
      onError={handleError}
      loading="lazy"
      decoding="async"
      {...props}
    />
  );
};
