'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const artStyles = [
  { id: 'pixel_art', name: 'Pixel Art', description: 'Retro-style low-resolution graphics' },
  { id: 'low_poly', name: 'Low Poly', description: 'Minimalist 3D with simple geometry' },
  { id: 'cartoon', name: 'Cartoon', description: 'Stylized, animated look' },
  { id: 'realistic', name: 'Realistic', description: 'High-fidelity realistic graphics' },
  { id: 'hand_drawn', name: 'Hand Drawn', description: 'Artistic, illustrated style' },
  { id: 'minimalist', name: 'Minimalist', description: 'Clean, simple geometric shapes' },
];

export function ArtStyleStep() {
  const { artStyle, setArtStyle } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Choose Art Style</CardTitle>
        <CardDescription>
          Select the visual aesthetic for your game
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          {artStyles.map((style) => (
            <Button
              key={style.id}
              variant={artStyle === style.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                artStyle === style.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setArtStyle(style.id)}
            >
              <span className="font-semibold">{style.name}</span>
              <span className="text-xs text-muted-foreground text-left">
                {style.description}
              </span>
            </Button>
          ))}
        </div>
      </CardContent>
    </div>
  );
}
