'use client';

// Примечание: в Zustand v5 нет экспорта `Provider` — стор работает напрямую через хуки
// (useWizardStore и т.п.), поэтому обёртка-провайдер не требуется.
export function Providers({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
