'use client';

import { useWizardStore } from '@/store/wizardStore';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';

export function DescriptionStep() {
  const { description, setDescription } = useWizardStore();

  return (
    <div className="space-y-4">
      <CardHeader>
        <CardTitle>Describe Your Game</CardTitle>
        <CardDescription>
          Provide additional details about your vision
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="description">Game Description</Label>
          <Textarea
            id="description"
            placeholder="Describe your game idea in detail. Include specific mechanics, story elements, or unique features you want to see..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="min-h-[200px]"
          />
          <p className="text-xs text-muted-foreground">
            This description will be used by AI agents to understand your vision and generate appropriate content.
          </p>
        </div>

        <div className="bg-muted p-4 rounded-lg">
          <h4 className="font-semibold mb-2">💡 Tips for better results:</h4>
          <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
            <li>Mention specific gameplay mechanics you want</li>
            <li>Describe the mood and atmosphere</li>
            <li>Include inspiration from existing games</li>
            <li>Specify any must-have features</li>
          </ul>
        </div>
      </CardContent>
    </div>
  );
}
