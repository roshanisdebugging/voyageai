import { createContext, useContext, useEffect } from 'react';

/** Where the single mic button sits; set by the main shell (see micLayout.tsx). */
export type MicLayout = { raised: boolean; inlineTarget: HTMLElement | null };
export const DEFAULT_MIC_LAYOUT: MicLayout = { raised: true, inlineTarget: null };

export const MicLayoutContext = createContext<{ layout: MicLayout; setLayout: (l: MicLayout) => void }>({
  layout: DEFAULT_MIC_LAYOUT,
  setLayout: () => {},
});

/** Called by the main shell; the layout goes back to the default when the shell unmounts. */
export const useMicLayout = (raised: boolean, inlineTarget: HTMLElement | null) => {
  const { setLayout } = useContext(MicLayoutContext);
  useEffect(() => {
    setLayout({ raised, inlineTarget });
  }, [raised, inlineTarget, setLayout]);
  useEffect(() => () => setLayout(DEFAULT_MIC_LAYOUT), [setLayout]);
};
