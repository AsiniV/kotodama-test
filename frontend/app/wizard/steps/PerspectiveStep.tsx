'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const perspectives = [
  { id: 'first_person', name: 'First Person', description: 'See through the player\'s eyes' },
  { id: 'third_person', name: 'Third Person', description: 'Camera follows behind character' },
  { id: 'top_down', name: 'Top Down', description: 'Bird\'s eye view from above' },
  { id: 'side_scroller', name: 'Side Scroller', description: '2D side view' },
  { id: 'isometric', name: 'Isometric', description: 'Angled 3D perspective' },
];

export function PerspectiveStep() {
  const { perspective, setPerspective } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Select Camera Perspective</CardTitle>
        <CardDescription>
          Choose how players will view your game world
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          {perspectives.map((p) => (
            <Button
              key={p.id}
              variant={perspective === p.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                perspective === p.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setPerspective(p.id)}
            >
              <span className="font-semibold">{p.name}</span>
              <span className="text-xs text-muted-foreground text-left">
                {p.description}
              </span>
            </Button>
          ))}
        </div>
      </CardContent>
    </div>
  );
}
