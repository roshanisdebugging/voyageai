import React, { useState } from 'react';
import { resolveImageUrl } from '../../utils/imageUtils';
import { pickImageSrc } from '../../utils/imageSources';
import { ImagePlaceholder } from './ImagePlaceholder';

interface SafeImageProps extends Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  src?: string | null;
  /** Category for the placeholder icon. */
  category?: string | null;
  /** Name shown on the placeholder (defaults to alt). */
  placeholderName?: string;
  containerClassName?: string;
}

/**
 * An image that never shows a broken-image icon and never swaps in a random photo: no src, or a src that fails
 * to load, renders <ImagePlaceholder> (gradient + category icon + name).
 */
export const SafeImage: React.FC<SafeImageProps> = ({
  src,
  alt = 'Image',
  className = 'w-full h-full object-cover',
  category,
  placeholderName,
  containerClassName = '',
  ...props
}) => {
  const resolved = resolveImageUrl(src);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const current = pickImageSrc(resolved, failedSrc);

  if (!current) {
    return <ImagePlaceholder name={placeholderName ?? alt} category={category} className={containerClassName} />;
  }

  return (
    <img
      src={current}
      alt={alt}
      className={className}
      onError={() => setFailedSrc(current)}
      loading="lazy"
      decoding="async"
      {...props}
    />
  );
};
