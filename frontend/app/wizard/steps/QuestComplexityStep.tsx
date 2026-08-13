'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const complexityLevels = [
  { id: 'none', name: 'None', description: 'No quests, pure exploration', credits: 0 },
  { id: 'simple', name: 'Simple', description: '1-2 linear quests', credits: 5 },
  { id: 'branching', name: 'Branching', description: '2-3 quests with choices', credits: 10 },
  { id: 'epic', name: 'Epic', description: '4-6 quests with dependencies and multiple endings', credits: 20 },
];

export function QuestComplexityStep() {
  const { questComplexity, setQuestComplexity } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Quest Complexity</CardTitle>
        <CardDescription>
          Define the depth and number of quests in your game
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="space-y-3">
          {complexityLevels.map((level) => (
            <Button
              key={level.id}
              variant={questComplexity === level.id ? 'default' : 'outline'}
              className={`w-full h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                questComplexity === level.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setQuestComplexity(level.id as any)}
            >
              <div className="flex items-center justify-between w-full">
                <span className="font-semibold">{level.name}</span>
                {level.credits > 0 && (
                  <span className="text-xs bg-primary/20 text-primary px-2 py-1 rounded">
                    +{level.credits} credits
                  </span>
                )}
              </div>
              <span className="text-xs text-muted-foreground text-left">
                {level.description}
              </span>
            </Button>
          ))}
        </div>
      </CardContent>
    </div>
  );
}
