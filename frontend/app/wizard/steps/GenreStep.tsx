'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const genres = [
  { id: 'action', name: 'Action', description: 'Fast-paced gameplay with physical challenges' },
  { id: 'adventure', name: 'Adventure', description: 'Story-driven exploration and puzzles' },
  { id: 'rpg', name: 'RPG', description: 'Character progression and stat management' },
  { id: 'platformer', name: 'Platformer', description: 'Jumping and climbing challenges' },
  { id: 'shooter', name: 'Shooter', description: 'Combat with ranged weapons' },
  { id: 'puzzle', name: 'Puzzle', description: 'Logic and problem-solving challenges' },
  { id: 'simulation', name: 'Simulation', description: 'Real-world system modeling' },
  { id: 'strategy', name: 'Strategy', description: 'Tactical planning and resource management' },
  { id: 'horror', name: 'Horror', description: 'Suspenseful and frightening experiences' },
  { id: 'visual_novel', name: 'Visual Novel', description: 'Narrative-focused with minimal gameplay' },
];

export function GenreStep() {
  const { genre, setGenre } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Choose Genre</CardTitle>
        <CardDescription>
          Select the primary genre for your game
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="grid grid-cols-2 gap-4">
          {genres.map((g) => (
            <Button
              key={g.id}
              variant={genre === g.id ? 'default' : 'outline'}
              className={`h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                genre === g.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setGenre(g.id)}
            >
              <span className="font-semibold">{g.name}</span>
              <span className="text-xs text-muted-foreground text-left">
                {g.description}
              </span>
            </Button>
          ))}
        </div>
      </CardContent>
    </div>
  );
}
