'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const scales = [
  { id: 'small', name: 'Small Scale', description: 'Single level or short experience (5-15 min)' },
  { id: 'medium', name: 'Medium Scale', description: 'Multiple levels or areas (30-60 min)' },
  { id: 'large', name: 'Large Scale', description: 'Extensive world with many areas (2-5 hours)' },
  { id: 'epic', name: 'Epic Scale', description: 'Massive open world (10+ hours)' },
];

export function ScaleStep() {
  const { scale, setScale } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Set Game Scale</CardTitle>
        <CardDescription>
          Define the scope and length of your game
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          {scales.map((s) => (
            <Button
              key={s.id}
              variant={scale === s.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                scale === s.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setScale(s.id)}
            >
              <span className="font-semibold">{s.name}</span>
              <span className="text-xs text-muted-foreground text-left">
                {s.description}
              </span>
            </Button>
          ))}
        </div>
      </CardContent>
    </div>
  );
}
