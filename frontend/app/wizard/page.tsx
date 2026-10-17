'use client';

import { GameWizard } from './GameWizard';

export default function WizardPage() {
  return (
    <main className="min-h-screen p-6">
      <div className="mx-auto max-w-4xl">
        <h1 className="mb-6 text-3xl font-bold">Game Creation Wizard</h1>
        <GameWizard />
      </div>
    </main>
  );
}
