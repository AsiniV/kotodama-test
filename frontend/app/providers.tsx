'use client';

import { Provider as ZustandProvider } from 'zustand';
import { useWizardStore } from '@/store/wizardStore';

let store: ReturnType<typeof useWizardStore> | null = null;

export function createStore() {
  if (!store) {
    store = useWizardStore;
  }
  return store;
}

export function Providers({ children }: { children: React.ReactNode }) {
  return <ZustandProvider store={createStore()}>{children}</ZustandProvider>;
}
