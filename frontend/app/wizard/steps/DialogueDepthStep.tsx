'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

const depthLevels = [
  { id: 'none', name: 'None', description: 'Silent game, no dialogues', credits: 0 },
  { id: 'linear', name: 'Linear', description: 'Simple NPC interactions, text boxes only', credits: 5 },
  { id: 'branching', name: 'Branching', description: 'Player choices affect dialogue flow (2-3 choices)', credits: 10 },
  { id: 'full_rpg', name: 'Full RPG', description: 'Complex dialogues with conditions, flags, quest triggers', credits: 20 },
];

export function DialogueDepthStep() {
  const { dialogueDepth, setDialogueDepth } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Dialogue Depth</CardTitle>
        <CardDescription>
          Define the complexity of NPC interactions and conversations
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <div className="space-y-3">
          {depthLevels.map((level) => (
            <Button
              key={level.id}
              variant={dialogueDepth === level.id ? 'default' : 'outline'}
              className={`w-full h-auto py-4 px-4 flex flex-col items-start gap-2 ${
                dialogueDepth === level.id ? 'ring-2 ring-primary' : ''
              }`}
              onClick={() => setDialogueDepth(level.id as any)}
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
