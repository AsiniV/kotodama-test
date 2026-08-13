'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const controls = [
  { id: 'keyboard', name: 'Keyboard Only', description: 'WASD + mouse/arrow keys' },
  { id: 'controller', name: 'Gamepad', description: 'Xbox/PlayStation controller' },
  { id: 'touch', name: 'Touch/Mobile', description: 'Tap and swipe controls' },
  { id: 'hybrid', name: 'Hybrid', description: 'Support for multiple input methods' },
];

export function ControlsStep() {
  const { controls: selectedControls, setControls } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Configure Controls</CardTitle>
        <CardDescription>
          Choose how players will interact with your game
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          {controls.map((c) => (
            <Button
              key={c.id}
              variant={selectedControls === c.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                selectedControls === c.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setControls(c.id)}
            >
              <span className="font-semibold">{c.name}</span>
              <span className="text-xs text-muted-foreground text-left">
                {c.description}
              </span>
            </Button>
          ))}
        </div>
      </CardContent>
    </div>
  );
}
