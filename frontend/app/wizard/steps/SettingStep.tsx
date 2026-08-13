'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const settings = [
  { id: 'fantasy', name: 'Fantasy', description: 'Magical worlds with mythical creatures' },
  { id: 'sci_fi', name: 'Sci-Fi', description: 'Futuristic technology and space' },
  { id: 'cyberpunk', name: 'Cyberpunk', description: 'High-tech dystopian future' },
  { id: 'post_apocalyptic', name: 'Post-Apocalyptic', description: 'Survival after civilization\'s end' },
  { id: 'modern', name: 'Modern Day', description: 'Contemporary real-world setting' },
  { id: 'historical', name: 'Historical', description: 'Based on real historical periods' },
  { id: 'horror', name: 'Horror', description: 'Dark, frightening environments' },
  { id: 'abstract', name: 'Abstract', description: 'Surreal, non-realistic worlds' },
];

export function SettingStep() {
  const { setting, setSetting } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Define Game Setting</CardTitle>
        <CardDescription>
          Choose the world where your game takes place
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          {settings.map((s) => (
            <Button
              key={s.id}
              variant={setting === s.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                setting === s.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setSetting(s.id)}
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
