'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Book, Plus } from 'lucide-react';

const loreOptions = [
  { id: 'cyberpunk', name: 'Cyberpunk City', description: 'High-tech dystopian future' },
  { id: 'fantasy', name: 'Fantasy Kingdom', description: 'Medieval world with magic' },
  { id: 'scifi_station', name: 'Space Station', description: 'Orbital research facility' },
  { id: 'post_apoc', name: 'Post-Apocalyptic', description: 'Survival in wasteland' },
  { id: 'horror_mansion', name: 'Haunted Mansion', description: 'Gothic horror setting' },
];

export function LoreStep() {
  const { loreId, setLoreId } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Select or Create Lore</CardTitle>
        <CardDescription>
          Choose a universe template or create your own custom lore
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-6">
        <div className="grid grid-cols-1 gap-4">
          {loreOptions.map((lore) => (
            <Button
              key={lore.id}
              variant={loreId === lore.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-6 flex flex-col items-start gap-2 ${
                loreId === lore.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setLoreId(lore.id)}
            >
              <div className="flex items-center gap-3">
                <Book className="w-5 h-5" />
                <span className="font-semibold">{lore.name}</span>
              </div>
              <span className="text-xs text-muted-foreground text-left ml-8">
                {lore.description}
              </span>
            </Button>
          ))}
        </div>

        <div className="border-t pt-4">
          <Button variant="outline" className="w-full gap-2">
            <Plus className="w-4 h-4" />
            Create Custom Lore Universe
          </Button>
          <p className="text-xs text-muted-foreground mt-2 text-center">
            Define your own characters, locations, and world rules
          </p>
        </div>
      </CardContent>
    </div>
  );
}
